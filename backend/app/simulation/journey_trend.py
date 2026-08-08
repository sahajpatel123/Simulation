"""
Journey trend — how a founder's funnel health evolves across simulations.

The journey-benchmark endpoints answer *"is this idea better than the
typical idea I (or the category) have run before?"*. This module answers the
follow-up question founders ask once they have several runs: *"am I actually
getting better at picking ideas?"*.

Every completed simulation (including the one the request is anchored on) is
reduced to a lightweight funnel summary via
:func:`app.simulation.journey_analytics.summarise_journey_matrices`, then
ordered oldest → newest to produce:

* a per-simulation point series (purchase probability, journey length,
  revisits, primary exit stage) with deltas and direction tags;
* best/worst runs, purchase statistics, a normalized OLS trend slope, and a
  coefficient-of-variation stability score;
* recent momentum (how many of the last transitions improved) and per-stage
  leak medians;
* deterministic, founder-facing insights and the anchor simulation's
  percentile rank against the founder's other simulations.

The module is pure (no DB, no I/O, no LLM), so it can be unit-tested with
plain dicts and reused for exports or digests later.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

from app.simulation.journey_benchmark import LEAK_STAGE_ORDER

# How many of the most recent points the momentum block looks at.
MOMENTUM_WINDOW: int = 5


def _finite(raw: Any) -> float | None:
    """Coerce a value to a finite float, or ``None`` when unusable."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


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
    """Normalise a leak dict to finite, non-negative floats for known stages."""
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


def _normalise_summary(summary: Any) -> dict[str, Any] | None:
    """Project a journey summary onto the fields the trend needs.

    A summary is usable only when every core metric is finite and in a valid
    range (purchase/abandon probabilities in ``[0, 1]``, non-negative
    expected steps and revisits). Anything else is malformed and is skipped,
    since a single bad value would contaminate the trend statistics.
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


def _created_at_string(raw: Any) -> str | None:
    """Render a DB datetime (or string) as an ISO string, or ``None``."""
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        return raw.isoformat()
    return str(raw)


def _direction(delta: float | None) -> str | None:
    if delta is None:
        return None
    if delta > 0.0:
        return "UP"
    if delta < 0.0:
        return "DOWN"
    return "FLAT"


def _linear_slope(values: list[float]) -> float | None:
    """Simple OLS slope of ``values`` over a 0-indexed x-axis."""
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _stability_score(values: list[float]) -> float | None:
    """Coefficient-of-variation-based stability in ``[0, 1]``."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    if mean == 0.0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / n
    std = variance ** 0.5
    cv = std / abs(mean)
    return round(1.0 / (1.0 + cv), 4)


def _purchase_stats(purchases: list[float]) -> dict[str, float | None]:
    """Min/max/mean/median/std rollup for purchase probabilities."""
    n = len(purchases)
    stats: dict[str, float | None] = {
        "count": float(n),
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "std": None,
    }
    if n == 0:
        return stats
    stats["min"] = round(min(purchases), 6)
    stats["max"] = round(max(purchases), 6)
    mean = sum(purchases) / n
    stats["mean"] = round(mean, 6)
    stats["median"] = round(statistics.median(purchases), 6)
    if n > 1:
        variance = sum((v - mean) ** 2 for v in purchases) / n
        stats["std"] = round(variance ** 0.5, 6)
    return stats


def _momentum(points: list[dict[str, Any]]) -> dict[str, float | int | None]:
    """Recent-transition momentum over the last ``MOMENTUM_WINDOW`` points."""
    recent = points[-MOMENTUM_WINDOW:]
    deltas = [p["delta_from_prev"] for p in recent[1:]]
    usable = [d for d in deltas if d is not None]
    improved = sum(1 for d in usable if d > 0.0)
    declined = sum(1 for d in usable if d < 0.0)
    flat = len(usable) - improved - declined
    share = (
        round(improved / len(usable) * 100.0, 2) if usable else None
    )
    return {
        "improved_count": improved,
        "declined_count": declined,
        "flat_count": flat,
        "improvement_share_pct": share,
        "latest_delta": (
            points[-1]["delta_from_prev"] if len(points) > 1 else None
        ),
    }


def _insights(
    points: list[dict[str, Any]],
    *,
    slope: float | None,
    momentum: dict[str, float | int | None],
    modal_exit: str | None,
    anchor_rank: float | None,
    anchor_tied_count: int = 0,
) -> list[str]:
    """Deterministic founder-facing insight strings."""
    if not points:
        return ["No journey-capable simulations found for this founder."]
    if len(points) == 1:
        return [
            "Run more simulations to see a journey trend — a single run "
            "has no direction yet."
        ]

    insights: list[str] = []
    latest = points[-1]
    median = statistics.median(
        p["purchase_probability"] for p in points
    )
    latest_pct = latest["purchase_probability"] * 100.0
    median_pct = median * 100.0
    if latest["purchase_probability"] > median:
        insights.append(
            f"The latest journey converts at {latest_pct:.2f}%, above your "
            f"median of {median_pct:.2f}%."
        )
    elif latest["purchase_probability"] < median:
        insights.append(
            f"The latest journey converts at {latest_pct:.2f}%, below your "
            f"median of {median_pct:.2f}%."
        )

    delta = latest["delta_from_prev"]
    if delta is not None:
        if delta > 0.0:
            insights.append(
                "Purchase probability improved by "
                f"+{delta * 100.0:.2f}pp vs the previous simulation."
            )
        elif delta < 0.0:
            insights.append(
                "Purchase probability declined by "
                f"{abs(delta) * 100.0:.2f}pp vs the previous simulation."
            )

    if slope is not None:
        if slope > 0.0:
            insights.append(
                f"Funnel conversion is trending up across your last "
                f"{len(points)} simulations."
            )
        elif slope < 0.0:
            insights.append(
                f"Funnel conversion is trending down across your last "
                f"{len(points)} simulations."
            )

    improved = int(momentum.get("improved_count") or 0)
    declined = int(momentum.get("declined_count") or 0)
    transition_count = improved + declined + int(
        momentum.get("flat_count") or 0
    )
    if transition_count >= 3 and improved >= 2 and improved >= declined:
        insights.append(
            f"Funnel conversion improved in {improved} of the last "
            f"{transition_count} transitions."
        )
    elif transition_count >= 3 and declined >= 2 and declined > improved:
        insights.append(
            f"Funnel conversion declined in {declined} of the last "
            f"{transition_count} transitions."
        )

    if modal_exit:
        insights.append(
            f"The most common exit across your simulations is at {modal_exit}."
        )

    if anchor_tied_count and anchor_tied_count == len(points) - 1:
        insights.append(
            "This simulation converts in line with all of your other "
            "simulations."
        )
    elif anchor_rank is not None:
        if anchor_rank >= 50.0:
            insights.append(
                "This simulation converts better than "
                f"{anchor_rank:.0f}% of your other simulations."
            )
        else:
            insights.append(
                "This simulation converts worse than "
                f"{100.0 - anchor_rank:.0f}% of your other simulations."
            )
    return insights[:6]


def build_journey_trend(
    rows: list[dict[str, Any]] | None,
    *,
    anchor_simulation_id: int,
    project_id: int,
) -> dict[str, Any]:
    """Compute the journey-trend rollup for a founder's simulations.

    ``rows`` shape (caller has already sorted ascending by ``created_at``):

        [
          {
            "simulation_id": int,
            "project_id": int,
            "created_at": datetime | str | None,
            "journey_summary": dict | None,
          },
          ...
        ]

    ``journey_summary`` is whatever
    :func:`app.simulation.journey_analytics.summarise_journey_matrices`
    returns; rows without a usable summary are counted in ``skipped_count``
    and excluded from every statistic.
    """
    raw_count = len(rows or [])
    points: list[dict[str, Any]] = []
    skipped_count = 0
    prev_purchase: float | None = None

    for row in rows or []:
        if not isinstance(row, dict):
            skipped_count += 1
            continue
        try:
            sim_id = int(row.get("simulation_id"))
        except (TypeError, ValueError):
            skipped_count += 1
            continue
        normalised = _normalise_summary(row.get("journey_summary"))
        if normalised is None:
            skipped_count += 1
            continue
        purchase = round(normalised["purchase_probability"], 6)
        delta = (
            round(purchase - prev_purchase, 6)
            if prev_purchase is not None
            else None
        )
        points.append(
            {
                "simulation_id": sim_id,
                "project_id": int(row.get("project_id") or project_id),
                "created_at": _created_at_string(row.get("created_at")),
                "purchase_probability": purchase,
                "abandon_probability": round(
                    normalised["abandon_probability"], 6
                ),
                "expected_steps_to_absorb": round(
                    normalised["expected_steps_to_absorb"], 4
                ),
                "expected_revisits": round(
                    normalised["expected_revisits"], 4
                ),
                "primary_exit_stage": normalised["primary_exit_stage"],
                "exit_stage_distribution": normalised[
                    "exit_stage_distribution"
                ],
                "delta_from_prev": delta,
                "direction": _direction(delta),
                "is_anchor": sim_id == anchor_simulation_id,
            }
        )
        prev_purchase = purchase

    purchases = [p["purchase_probability"] for p in points]
    slope = _linear_slope(purchases)
    momentum = _momentum(points)

    best_point: dict[str, Any] | None = None
    worst_point: dict[str, Any] | None = None
    for point in points:
        if (
            best_point is None
            or point["purchase_probability"] > best_point["purchase_probability"]
        ):
            best_point = point
        if (
            worst_point is None
            or point["purchase_probability"] < worst_point["purchase_probability"]
        ):
            worst_point = point

    exit_counts = Counter(
        p["primary_exit_stage"] for p in points if p["primary_exit_stage"]
    )
    most_common_exit: str | None = None
    if exit_counts:
        top_count = max(exit_counts.values())
        most_common_exit = sorted(
            stage
            for stage, count in exit_counts.items()
            if count == top_count
        )[0]

    stage_leak_medians: dict[str, float] = {}
    for stage in LEAK_STAGE_ORDER:
        values = [p["exit_stage_distribution"].get(stage, 0.0) for p in points]
        stage_leak_medians[stage] = (
            round(statistics.median(values), 6) if values else 0.0
        )

    anchor_rank: float | None = None
    anchor_tied_count = 0
    anchor_point = next(
        (p for p in points if p["simulation_id"] == anchor_simulation_id),
        None,
    )
    if anchor_point is not None:
        others = [
            p["purchase_probability"]
            for p in points
            if p["simulation_id"] != anchor_simulation_id
        ]
        if others:
            anchor_purchase = anchor_point["purchase_probability"]
            below = sum(1 for v in others if v < anchor_purchase)
            tied = sum(1 for v in others if v == anchor_purchase)
            anchor_tied_count = tied
            # Ties count half a rank (midrank method), so an anchor that
            # matches every other simulation is never reported as "worse
            # than 100% of your other simulations".
            anchor_rank = round(
                (below + 0.5 * tied) / len(others) * 100.0,
                2,
            )

    return {
        "simulation_id": anchor_simulation_id,
        "project_id": project_id,
        "status": "COMPLETED",
        "points": points,
        "summary": {
            "included_count": len(points),
            "raw_count": raw_count,
            "skipped_count": skipped_count,
            "purchase_stats": _purchase_stats(purchases),
            "best_point": best_point,
            "worst_point": worst_point,
            "trend_slope": slope,
            "stability_score": _stability_score(purchases),
            "momentum": momentum,
            "most_common_primary_exit_stage": most_common_exit,
            "stage_leak_medians": stage_leak_medians,
            "latest_stage_leaks": (
                points[-1]["exit_stage_distribution"] if points else {}
            ),
        },
        "insights": _insights(
            points,
            slope=slope,
            momentum=momentum,
            modal_exit=most_common_exit,
            anchor_rank=anchor_rank,
            anchor_tied_count=anchor_tied_count,
        ),
        "anchor_percentile_rank": anchor_rank,
        "generated_at": "",
    }


__all__ = [
    "MOMENTUM_WINDOW",
    "build_journey_trend",
]
