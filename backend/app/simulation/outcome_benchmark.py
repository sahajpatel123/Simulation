"""
Real-world outcome peer benchmark — ranking a launched project's actual
conversion against other founders' reported outcomes in the same category.

The journey-benchmark endpoints compare *simulated* funnels. This module adds
the post-launch counterpart: once a founder records a real outcome
(``founder_outcomes.actual_conversion_rate``), it ranks that outcome against
peer outcomes from other launched projects in the same product category and
produces a distribution (min / p25 / median / p75 / max / mean), a fair
midrank percentile, a verdict, and founder-facing insights.

The module is pure (no DB, no I/O, no LLM), so it can be unit-tested with
plain dicts and reused for exports or digests later.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

# How many peer outcomes the route is allowed to scan before the distribution
# becomes approximate. Keeps the benchmark query bounded.
MAX_PEERS: int = 500

# Minimum peer count before the ranking is treated as statistically
# meaningful. Below this, insights add a "directional only" caveat.
MIN_PEERS_FOR_SUFFICIENT_DATA: int = 5

VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VERDICT_TOP_QUARTILE: str = "TOP_QUARTILE"
VERDICT_ABOVE_MEDIAN: str = "ABOVE_MEDIAN"
VERDICT_AT_MEDIAN: str = "AT_MEDIAN"
VERDICT_BELOW_MEDIAN: str = "BELOW_MEDIAN"
VERDICT_BOTTOM_QUARTILE: str = "BOTTOM_QUARTILE"
VALID_VERDICTS: frozenset[str] = frozenset({
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_TOP_QUARTILE,
    VERDICT_ABOVE_MEDIAN,
    VERDICT_AT_MEDIAN,
    VERDICT_BELOW_MEDIAN,
    VERDICT_BOTTOM_QUARTILE,
})

# Signal severity buckets — kept aligned with the other dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_rate(raw: Any) -> float | None:
    """Coerce a value to a finite float in ``[0, 1]`` or return ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value


def _safe_int(raw: Any) -> int | None:
    """Coerce a value to an int or return ``None``.

    Rejects booleans, non-integral floats (``1.5`` would otherwise
    silently truncate to ``1``) and values that cannot be parsed
    (including floats encoded as strings such as ``"1.5"``), so a
    malformed row can never raise inside the builder and 500 the endpoint.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float) and not raw.is_integer():
        return None
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(value: Any) -> str | None:
    """Render a DB datetime (or string) as an ISO string, or ``None``."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _category_label(category: str | None) -> str:
    """Normalise a product category into a safe display label."""
    label = re.sub(r"[^a-z0-9 _-]", "", (category or "idea").strip().lower())
    label = label.replace("_", " ").strip()
    return label[:40] or "idea"


def _percentile(sorted_rates: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_rates:
        raise ValueError("percentile requires at least one value")
    if len(sorted_rates) == 1:
        return sorted_rates[0]
    position = (len(sorted_rates) - 1) * pct / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_rates) - 1)
    fraction = position - lower
    return sorted_rates[lower] + (
        sorted_rates[upper] - sorted_rates[lower]
    ) * fraction


def _midrank_percentile(value: float, rates: list[float]) -> float | None:
    """Share of peers below ``value``, with ties counting half a rank."""
    if not rates:
        return None
    below = sum(1 for rate in rates if rate < value)
    tied = sum(1 for rate in rates if rate == value)
    return round((below + 0.5 * tied) / len(rates) * 100.0, 2)


def _median_comparison(current: float, median: float) -> str:
    """ABOVE / AT / BELOW comparison against the peer median."""
    if current == median:
        return "AT"
    return "ABOVE" if current > median else "BELOW"


def _verdict(
    rank: float | None,
    current: float,
    median: float,
) -> str:
    """Map percentile rank + median comparison to a verdict label."""
    if rank is None:
        return VERDICT_INSUFFICIENT_DATA
    comparison = _median_comparison(current, median)
    if comparison == "AT":
        return VERDICT_AT_MEDIAN
    if comparison == "ABOVE":
        return (
            VERDICT_TOP_QUARTILE
            if rank >= 75.0
            else VERDICT_ABOVE_MEDIAN
        )
    return (
        VERDICT_BOTTOM_QUARTILE
        if rank < 25.0
        else VERDICT_BELOW_MEDIAN
    )


def _distribution(rates: list[float]) -> dict[str, float | None]:
    """Min / p25 / median / p75 / max / mean rollup for peer rates."""
    if not rates:
        return {
            "peer_count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
            "mean": None,
        }
    ordered = sorted(rates)
    return {
        "peer_count": len(rates),
        "min": round(ordered[0], 6),
        "p25": round(_percentile(ordered, 25.0), 6),
        "median": round(statistics.median(ordered), 6),
        "p75": round(_percentile(ordered, 75.0), 6),
        "max": round(ordered[-1], 6),
        "mean": round(sum(ordered) / len(ordered), 6),
    }


def _insights(
    current: dict[str, Any],
    label: str,
    rates: list[float],
    rank: float | None,
    median: float,
    predicted: float | None,
    data_sufficient: bool,
) -> list[str]:
    """Deterministic founder-facing insight strings."""
    insights: list[str] = []
    n = len(rates)
    if n:
        if rank is not None:
            if rank >= 100.0:
                insights.append(
                    f"Outperforms every one of {n} reported {label} "
                    "launches on TheCee."
                )
            elif rank <= 0.0:
                insights.append(
                    f"Every one of {n} reported {label} launches converted "
                    "at least as well as this one."
                )
            else:
                insights.append(
                    f"Ranks above {rank:.1f}% of {n} reported {label} "
                    "launches on TheCee."
                )

        delta_pp = (current["actual_conversion_rate"] - median) * 100.0
        if abs(delta_pp) < 0.05:
            insights.append(
                f"Actual conversion ({current['actual_conversion_rate']:.2%}) "
                f"is right in line with the median {label} launch "
                f"({median:.2%})."
            )
        else:
            direction = "above" if delta_pp > 0 else "below"
            insights.append(
                f"Actual conversion is {abs(delta_pp):.2f}pp {direction} the "
                f"median {label} launch ({median:.2%})."
            )

    if predicted is not None:
        gap = current["actual_conversion_rate"] - predicted
        if abs(gap) < 0.005:
            insights.append(
                f"The simulation predicted {predicted:.2%}; actual conversion "
                "matched within 0.5pp."
            )
        else:
            direction = "higher" if gap > 0 else "lower"
            insights.append(
                f"The simulation predicted {predicted:.2%}; actual conversion "
                f"landed {abs(gap) * 100.0:.2f}pp {direction}."
            )

    if not data_sufficient:
        insights.append(
            f"Only {n} peer outcome(s) so far — treat this ranking as "
            "directional."
        )
    return insights[:4]


def _key_signals(
    has_data: bool,
    has_category: bool,
    has_peers: bool,
    verdict: str,
) -> list[dict[str, str]]:
    """Compose the dashboard key-signal tile for the benchmark."""
    if not has_data:
        return [{
            "label": "outcome_benchmark",
            "value": "NO_OUTCOME",
            "severity": SIGNAL_WATCH,
            "display": "Record a founder outcome to benchmark this launch.",
        }]
    if not has_category:
        return [{
            "label": "outcome_benchmark",
            "value": "NO_CATEGORY",
            "severity": SIGNAL_WATCH,
            "display": "Run a simulation to unlock the real-world benchmark.",
        }]
    if not has_peers:
        return [{
            "label": "outcome_benchmark",
            "value": "NO_PEERS",
            "severity": SIGNAL_WATCH,
            "display": "No comparable peer outcomes yet.",
        }]

    if verdict in {
        VERDICT_TOP_QUARTILE,
        VERDICT_ABOVE_MEDIAN,
        VERDICT_AT_MEDIAN,
    }:
        severity = SIGNAL_OK
    elif verdict == VERDICT_BELOW_MEDIAN:
        severity = SIGNAL_WATCH
    else:
        severity = SIGNAL_CRITICAL
    return [{
        "label": "outcome_benchmark",
        "value": verdict,
        "severity": severity,
        "display": (
            "Real-world conversion verdict: "
            f"{verdict.replace('_', ' ').title()}"
        ),
    }]


def build_outcome_benchmark(
    current_outcome: dict[str, Any] | None,
    peer_outcomes: list[dict[str, Any]] | None,
    *,
    category: str | None = None,
) -> dict[str, Any]:
    """Compose the real-world outcome peer-benchmark payload.

    Args:
        current_outcome: the project's most recent ``founder_outcomes`` row
            (or ``None``). Must expose ``id`` (or ``outcome_id``) and
            ``actual_conversion_rate``; ``predicted_conversion_rate``,
            ``simulation_id``, ``project_id``, ``days_since_launch``,
            ``data_confidence``, ``launched`` and ``created_at`` are
            optional and echoed defensively.
        peer_outcomes: list of other launched outcomes in the same product
            category. Each row must expose ``actual_conversion_rate`` and
            optionally ``product_changed_since_sim`` (rows where the product
            changed are excluded from the distribution and counted in meta).
        category: product-category label for the cohort (``None`` when the
            project has no detected category).

    Returns:
        A dict matching :class:`OutcomeBenchmarkOut`.
    """
    label = _category_label(category)
    current: dict[str, Any] | None = None
    has_data = False

    if isinstance(current_outcome, dict):
        actual = _safe_rate(current_outcome.get("actual_conversion_rate"))
        outcome_id = _safe_int(
            current_outcome.get("outcome_id")
            or current_outcome.get("id")
        )
        if actual is not None and outcome_id is not None:
            has_data = True
            predicted = _safe_rate(
                current_outcome.get("predicted_conversion_rate")
            )
            current = {
                "outcome_id": outcome_id,
                "simulation_id": _safe_int(
                    current_outcome.get("simulation_id")
                ),
                "project_id": _safe_int(current_outcome.get("project_id")),
                "actual_conversion_rate": round(actual, 6),
                "predicted_conversion_rate": (
                    round(predicted, 6) if predicted is not None else None
                ),
                "days_since_launch": max(
                    _safe_int(current_outcome.get("days_since_launch")) or 0,
                    0,
                ),
                "data_confidence": (
                    str(current_outcome["data_confidence"])
                    if current_outcome.get("data_confidence")
                    else None
                ),
                "launched": bool(current_outcome.get("launched")),
                "recorded_at": _iso(current_outcome.get("created_at")),
            }

    peers_usable: list[float] = []
    peers_skipped_invalid = 0
    peers_skipped_product_changed = 0
    for raw in peer_outcomes or []:
        if not isinstance(raw, dict):
            peers_skipped_invalid += 1
            continue
        if bool(raw.get("product_changed_since_sim")):
            peers_skipped_product_changed += 1
            continue
        rate = _safe_rate(raw.get("actual_conversion_rate"))
        if rate is None:
            peers_skipped_invalid += 1
            continue
        peers_usable.append(rate)

    distribution = _distribution(peers_usable)
    median = distribution["median"]
    rank: float | None = None
    if current is not None and peers_usable and median is not None:
        rank = _midrank_percentile(
            current["actual_conversion_rate"],
            peers_usable,
        )

    verdict = VERDICT_INSUFFICIENT_DATA
    median_comparison: str | None = None
    if current is not None and median is not None:
        verdict = _verdict(
            rank,
            current["actual_conversion_rate"],
            median,
        )
        median_comparison = _median_comparison(
            current["actual_conversion_rate"],
            median,
        )

    data_sufficient = (
        len(peers_usable) >= MIN_PEERS_FOR_SUFFICIENT_DATA
    )
    has_category = bool(category and str(category).strip())

    if not has_data:
        insights = [
            "Record a founder outcome for this project to see how its "
            "real-world conversion ranks against peer launches."
        ]
        narrative = (
            "No founder outcome recorded yet — the real-world benchmark "
            "unlocks after you report how launch went."
        )
    elif not has_category:
        insights = [
            "No product category detected for this project — run a "
            "simulation so TheCee can benchmark this launch against peers."
        ]
        narrative = (
            "Benchmark unavailable until the project has a product category."
        )
    elif not peers_usable:
        insights = [
            f"No comparable launched outcomes in {label} yet — check back "
            "as more founders report results."
        ]
        narrative = (
            f"No peer outcomes in {label} yet — this launch has nothing "
            "to benchmark against."
        )
    else:
        insights = _insights(
            current or {},
            label,
            peers_usable,
            rank,
            median or 0.0,
            (current or {}).get("predicted_conversion_rate"),
            data_sufficient,
        )
        narrative = insights[0] if insights else ""

    return {
        "has_data": has_data,
        "category": category,
        "current": current,
        "distribution": distribution,
        "percentile_rank": rank,
        "verdict": verdict,
        "median_comparison": median_comparison,
        "narrative": narrative,
        "insights": insights,
        "key_signals": _key_signals(
            has_data,
            has_category,
            bool(peers_usable),
            verdict,
        ),
        "meta": {
            "benchmark_scope": (
                "other launched projects in the same product category "
                "across TheCee"
            ),
            "peers_scanned": len(peer_outcomes or []),
            "peers_usable": len(peers_usable),
            "peers_skipped_invalid": peers_skipped_invalid,
            "peers_skipped_product_changed": peers_skipped_product_changed,
            "data_sufficient": data_sufficient,
        },
    }


__all__ = [
    "MAX_PEERS",
    "MIN_PEERS_FOR_SUFFICIENT_DATA",
    "VERDICT_INSUFFICIENT_DATA",
    "VERDICT_TOP_QUARTILE",
    "VERDICT_ABOVE_MEDIAN",
    "VERDICT_AT_MEDIAN",
    "VERDICT_BELOW_MEDIAN",
    "VERDICT_BOTTOM_QUARTILE",
    "VALID_VERDICTS",
    "build_outcome_benchmark",
]
