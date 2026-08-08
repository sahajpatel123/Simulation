"""
Journey benchmark — how one simulation's funnel compares to a founder's own history.

The journey-analytics endpoint answers *"how does this idea convert and where
does its funnel leak?"*. This module answers the question founders ask next:
*"is this idea actually better than my previous ideas?"*

The route layer supplies the current simulation's journey payload and the
user's other completed simulations (as per-cluster matrix + weight raw
payloads); this module reduces every simulation to a lightweight funnel
summary via :func:`app.simulation.journey_analytics.summarise_journey_matrices`
and computes a deterministic benchmark:

* cohort distribution (median/mean/percentiles of purchase probability,
  median journey length and revisits, per-stage leak medians, modal primary
  exit stage);
* the current simulation's percentile rank against that cohort;
* a short list of founder-facing insights.

The module is pure (no DB, no I/O, no LLM), so it can be unit-tested with
plain dicts and reused for exports or digests later.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

from app.simulation.journey_analytics import (
    TRANSIENT_STATES,
    summarise_journey_matrices,
)

# Deterministic stage order for leak tables (RETURN is unreachable before
# absorption and never carries exits).
LEAK_STAGE_ORDER: tuple[str, ...] = tuple(
    s.value for s in TRANSIENT_STATES if s.value != "RETURN"
)


def _finite(raw: Any) -> float | None:
    """Coerce a value to a finite float, or ``None`` when unusable."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; deterministic for any sample size."""
    if not sorted_values:
        return None
    index = max(
        0,
        min(
            len(sorted_values) - 1,
            math.ceil(pct / 100.0 * len(sorted_values)) - 1,
        ),
    )
    return sorted_values[index]


def _primary_exit_stage(distribution: Any) -> str | None:
    """Stage with the largest expected exit share, or ``None`` when empty."""
    if not isinstance(distribution, dict):
        return None
    cleaned: dict[str, float] = {}
    for stage, raw in distribution.items():
        if str(stage) not in LEAK_STAGE_ORDER:
            continue
        parsed = _finite(raw)
        if parsed is not None:
            cleaned[str(stage)] = parsed
    if not cleaned:
        return None
    best = max(cleaned, key=lambda stage: cleaned[stage])
    return best if cleaned[best] > 0.0 else None


def _cleaned_leak_distribution(raw: Any) -> dict[str, float]:
    """Normalise a leak dict to finite floats, keeping only known stages.

    Unknown stage names (e.g. from a hand-edited or legacy persisted
    payload) are dropped so they can never surface as a primary exit stage
    or in insight strings.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, float] = {}
    for stage, value in raw.items():
        if str(stage) not in LEAK_STAGE_ORDER:
            continue
        parsed = _finite(value)
        if parsed is not None and parsed >= 0.0:
            cleaned[str(stage)] = parsed
    return cleaned


def _normalise_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Project a raw cohort summary onto the fields the benchmark needs.

    Entries are usable only when every core metric is finite and in a valid
    range (purchase/abandon probabilities in ``[0, 1]``, non-negative
    expected steps and revisits). Anything else is malformed and is skipped
    by the caller, since a single bad value would otherwise contaminate the
    cohort medians.
    """
    if not isinstance(summary, dict):
        return None
    purchase = _finite(summary.get("purchase_probability"))
    if purchase is None or purchase < 0.0 or purchase > 1.0:
        return None
    abandon = _finite(summary.get("abandon_probability"))
    if abandon is None or abandon < 0.0 or abandon > 1.0:
        return None
    steps = _finite(summary.get("expected_steps_to_absorb"))
    if steps is None or steps < 0.0:
        return None
    revisits = _finite(summary.get("expected_revisits"))
    if revisits is None or revisits < 0.0:
        return None
    leak_distribution = _cleaned_leak_distribution(
        summary.get("exit_stage_distribution")
    )
    return {
        "purchase_probability": purchase,
        "abandon_probability": abandon,
        "expected_steps_to_absorb": steps,
        "expected_revisits": revisits,
        "exit_stage_distribution": leak_distribution,
        "primary_exit_stage": _primary_exit_stage(leak_distribution),
    }


def _current_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise the current simulation's journey payload.

    Non-finite values default to zero, and finite-but-out-of-range values
    are clamped into the response schema's valid ranges so a corrupt or
    legacy persisted payload can never turn this endpoint into a 500.
    """
    leak_raw = payload.get("exit_stage_distribution") if isinstance(
        payload.get("exit_stage_distribution"),
        dict,
    ) else {}
    purchase = _finite(payload.get("purchase_probability")) or 0.0
    abandon = _finite(payload.get("abandon_probability")) or 0.0
    steps = _finite(payload.get("expected_steps_to_absorb")) or 0.0
    revisits = _finite(payload.get("expected_revisits")) or 0.0
    leak_distribution = _cleaned_leak_distribution(leak_raw)
    return {
        "purchase_probability": max(0.0, min(1.0, purchase)),
        "abandon_probability": max(0.0, min(1.0, abandon)),
        "expected_steps_to_absorb": max(0.0, steps),
        "expected_revisits": max(0.0, revisits),
        "exit_stage_distribution": leak_distribution,
        "primary_exit_stage": _primary_exit_stage(leak_distribution),
    }


def _distribution(cohort: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cohort funnel statistics (empty cohort → all ``None``)."""
    if not cohort:
        return {
            "median_purchase_probability": None,
            "mean_purchase_probability": None,
            "p25_purchase_probability": None,
            "p75_purchase_probability": None,
            "min_purchase_probability": None,
            "max_purchase_probability": None,
            "median_expected_steps": None,
            "median_expected_revisits": None,
            "most_common_primary_exit_stage": None,
            "stage_leak_medians": {},
        }

    rates = sorted(item["purchase_probability"] for item in cohort)
    stage_leak_medians: dict[str, float] = {}
    for stage in LEAK_STAGE_ORDER:
        values = [
            item["exit_stage_distribution"].get(stage, 0.0)
            for item in cohort
        ]
        stage_leak_medians[stage] = round(statistics.median(values), 6)

    exit_counts = Counter(
        item["primary_exit_stage"]
        for item in cohort
        if item["primary_exit_stage"]
    )
    most_common: str | None = None
    if exit_counts:
        top_count = max(exit_counts.values())
        most_common = sorted(
            stage
            for stage, count in exit_counts.items()
            if count == top_count
        )[0]

    return {
        "median_purchase_probability": round(statistics.median(rates), 6),
        "mean_purchase_probability": round(statistics.fmean(rates), 6),
        "p25_purchase_probability": round(_percentile(rates, 25.0), 6),
        "p75_purchase_probability": round(_percentile(rates, 75.0), 6),
        "min_purchase_probability": round(rates[0], 6),
        "max_purchase_probability": round(rates[-1], 6),
        "median_expected_steps": round(
            statistics.median(
                item["expected_steps_to_absorb"] for item in cohort
            ),
            4,
        ),
        "median_expected_revisits": round(
            statistics.median(item["expected_revisits"] for item in cohort),
            4,
        ),
        "most_common_primary_exit_stage": most_common,
        "stage_leak_medians": stage_leak_medians,
    }


def _percentile_rank(value: float, rates: list[float]) -> float | None:
    """Share of cohort simulations converting strictly below ``value``."""
    if not rates:
        return None
    below = sum(1 for rate in rates if rate < value)
    return round(below / len(rates) * 100.0, 2)


def _insights(
    current: dict[str, Any],
    cohort: list[dict[str, Any]],
    percentile_rank: float | None,
    distribution: dict[str, Any],
) -> list[str]:
    """Founder-facing, deterministic insight strings."""
    if not cohort:
        return [
            "No previous journey-capable simulations yet — run and complete "
            "another simulation to unlock funnel benchmarks."
        ]

    insights: list[str] = []
    rates = [item["purchase_probability"] for item in cohort]
    median_rate = statistics.median(rates)
    if percentile_rank is not None:
        if percentile_rank >= 100.0:
            insights.append(
                "Outperforms every benchmarked simulation in your portfolio."
            )
        elif percentile_rank <= 0.0:
            insights.append(
                "Every benchmarked simulation in your portfolio converts at "
                "least as well as this one."
            )
        else:
            insights.append(
                f"Ranks above {percentile_rank:.1f}% of your "
                f"{len(cohort)} benchmarked simulations."
            )

    delta_pp = (current["purchase_probability"] - median_rate) * 100.0
    if abs(delta_pp) < 0.05:
        insights.append(
            f"Purchase probability ({current['purchase_probability']:.1%}) is "
            f"right in line with your median idea ({median_rate:.1%})."
        )
    else:
        direction = "above" if delta_pp > 0 else "below"
        insights.append(
            f"Purchase probability is {abs(delta_pp):.1f}pp {direction} your "
            f"median idea ({median_rate:.1%})."
        )

    current_primary = current["primary_exit_stage"]
    modal_primary = distribution["most_common_primary_exit_stage"]
    if current_primary and modal_primary:
        if current_primary == modal_primary:
            insights.append(
                f"Your biggest leak ({current_primary} → ABANDON) matches "
                "your typical idea."
            )
        else:
            insights.append(
                f"Your biggest leak is {current_primary} → ABANDON; your "
                f"typical idea leaks most at {modal_primary} → ABANDON."
            )

    median_steps = statistics.median(
        item["expected_steps_to_absorb"] for item in cohort
    )
    current_steps = current["expected_steps_to_absorb"]
    if abs(current_steps - median_steps) >= 0.1:
        direction = "longer" if current_steps > median_steps else "shorter"
        insights.append(
            f"Consumers spend {current_steps:.1f} steps in the funnel — "
            f"{direction} than your {median_steps:.1f}-step median journey."
        )
    return insights


def build_journey_benchmark(
    current_payload: dict[str, Any],
    cohort_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the full journey-benchmark payload.

    ``current_payload`` is the journey-analytics payload for the simulation
    being benchmarked; ``cohort_summaries`` are the lightweight funnel
    summaries (from :func:`summarise_journey_matrices`) of every other
    completed simulation in the cohort. Malformed or non-finite cohort
    entries are skipped and counted in ``meta``.
    """
    current = _current_summary(current_payload)

    cohort: list[dict[str, Any]] = []
    skipped_invalid = 0
    for summary in cohort_summaries or []:
        normalised = _normalise_summary(summary)
        if normalised is None:
            skipped_invalid += 1
            continue
        cohort.append(normalised)

    distribution = _distribution(cohort)
    percentile_rank = _percentile_rank(
        current["purchase_probability"],
        [item["purchase_probability"] for item in cohort],
    )
    insights = _insights(current, cohort, percentile_rank, distribution)

    return {
        "cohort_size": len(cohort),
        "current": current,
        "distribution": distribution,
        "percentile_rank": percentile_rank,
        "insights": insights,
        "meta": {
            "skipped_invalid_summaries": skipped_invalid,
            "cohort_scope": (
                "other completed simulations owned by the user with "
                "per-cluster journey data"
            ),
        },
    }


__all__ = [
    "LEAK_STAGE_ORDER",
    "build_journey_benchmark",
    "summarise_journey_matrices",
]
