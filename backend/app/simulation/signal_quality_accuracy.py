"""Measure whether stronger simulation inputs produce more accurate outcomes.

The calibration history already persists predicted conversion, actual
conversion and the run's signal quality. This pure builder turns those rows
into a founder-facing calibration check across the same QUARANTINED / PARTIAL /
FULL tiers used by the learning engine.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Mapping

from app.simulation.scored_assumption import signal_quality_tier

VERDICT_ALIGNED: str = "QUALITY_ALIGNED"
VERDICT_INVERTED: str = "QUALITY_INVERTED"
VERDICT_FLAT: str = "FLAT"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

TIER_ORDER: tuple[str, ...] = ("QUARANTINED", "PARTIAL", "FULL")
TIER_BOUNDS: dict[str, tuple[float, float]] = {
    "QUARANTINED": (0.0, 0.249999),
    "PARTIAL": (0.25, 0.499999),
    "FULL": (0.5, 1.0),
}

# Avoid drawing a directional conclusion from one lucky outcome per tier.
MIN_OUTCOMES_PER_TIER: int = 2
# Changes smaller than half a percentage point are treated as practically flat.
MIN_MEANINGFUL_MAE_DELTA: float = 0.005
EXACT_ERROR_TOLERANCE: float = 1e-12


def _value(row: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _rate(value: Any) -> float | None:
    """Return a finite conversion/signal rate in ``[0, 1]``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        return None
    return parsed


def _bucket_payload(tier: str, errors: list[float]) -> dict[str, Any]:
    minimum, maximum = TIER_BOUNDS[tier]
    if not errors:
        return {
            "tier": tier,
            "minimum_signal_quality": minimum,
            "maximum_signal_quality": maximum,
            "outcome_count": 0,
            "mean_absolute_error": None,
            "root_mean_square_error": None,
            "mean_signed_error": None,
            "overprediction_count": 0,
            "underprediction_count": 0,
            "exact_count": 0,
        }

    count = len(errors)
    mae = sum(abs(error) for error in errors) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    signed = sum(errors) / count
    return {
        "tier": tier,
        "minimum_signal_quality": minimum,
        "maximum_signal_quality": maximum,
        "outcome_count": count,
        "mean_absolute_error": round(mae, 6),
        "root_mean_square_error": round(rmse, 6),
        "mean_signed_error": round(signed, 6),
        "overprediction_count": sum(
            1 for error in errors if error > EXACT_ERROR_TOLERANCE
        ),
        "underprediction_count": sum(
            1 for error in errors if error < -EXACT_ERROR_TOLERANCE
        ),
        "exact_count": sum(
            1 for error in errors if abs(error) <= EXACT_ERROR_TOLERANCE
        ),
    }


def _message(
    verdict: str,
    from_tier: str | None,
    to_tier: str | None,
    improvement: float | None,
) -> tuple[str, list[str]]:
    if verdict == VERDICT_INSUFFICIENT:
        return (
            "Not enough comparable real-world outcomes yet to test whether "
            "stronger input evidence improves prediction accuracy.",
            [
                f"Record at least {MIN_OUTCOMES_PER_TIER} outcomes in two signal-quality "
                "tiers to unlock a directional comparison."
            ],
        )

    delta = improvement or 0.0
    if verdict == VERDICT_ALIGNED:
        return (
            f"Prediction error fell by {delta:.1%} from {from_tier} to {to_tier} "
            "signal quality, so the evidence score is behaving as intended.",
            [
                "Keep validating high-impact assumptions before each run; your history "
                "shows that stronger inputs improve forecast accuracy."
            ],
        )
    if verdict == VERDICT_INVERTED:
        return (
            f"Prediction error rose by {abs(delta):.1%} from {from_tier} to {to_tier} "
            "signal quality; the quality score is not yet aligned with observed accuracy.",
            [
                "Review the higher-quality runs for product changes, stale evidence, or "
                "outcome-window mismatches before trusting their narrower confidence."
            ],
        )
    return (
        f"Prediction error changed by only {abs(delta):.1%} from {from_tier} to "
        f"{to_tier} signal quality, which is not yet a meaningful difference.",
        [
            "Collect more outcomes across distinct evidence tiers before changing how "
            "you interpret the signal-quality score."
        ],
    )


def build_signal_quality_accuracy(
    rows: list[Mapping[str, Any] | Any] | None,
    *,
    user_id: int,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build an accuracy-by-signal-quality digest from calibration rows.

    Malformed rows are discarded rather than coerced into zero-error evidence.
    Signed error is ``predicted - actual``: positive means over-prediction.
    The comparison uses the lowest and highest populated tiers, provided each
    contains at least :data:`MIN_OUTCOMES_PER_TIER` valid outcomes.
    """
    source_rows = rows or []
    errors_by_tier: dict[str, list[float]] = {tier: [] for tier in TIER_ORDER}
    discarded = 0
    for row in source_rows:
        predicted = _rate(_value(row, "predicted_conversion"))
        actual = _rate(_value(row, "actual_conversion"))
        quality = _rate(_value(row, "signal_quality_at_run"))
        if predicted is None or actual is None or quality is None:
            discarded += 1
            continue
        tier = signal_quality_tier(quality)
        errors_by_tier[tier].append(predicted - actual)

    buckets = [
        _bucket_payload(tier, errors_by_tier[tier]) for tier in TIER_ORDER
    ]
    populated = [bucket for bucket in buckets if bucket["outcome_count"] > 0]
    comparable = [
        bucket
        for bucket in populated
        if bucket["outcome_count"] >= MIN_OUTCOMES_PER_TIER
    ]

    from_tier: str | None = None
    to_tier: str | None = None
    improvement: float | None = None
    relative_reduction: float | None = None
    verdict = VERDICT_INSUFFICIENT
    if len(comparable) >= 2:
        lower = comparable[0]
        higher = comparable[-1]
        lower_mae = float(lower["mean_absolute_error"])
        higher_mae = float(higher["mean_absolute_error"])
        improvement = round(lower_mae - higher_mae, 6)
        from_tier = str(lower["tier"])
        to_tier = str(higher["tier"])
        if lower_mae > 0.0:
            relative_reduction = round(improvement / lower_mae, 6)
        if improvement >= MIN_MEANINGFUL_MAE_DELTA:
            verdict = VERDICT_ALIGNED
        elif improvement <= -MIN_MEANINGFUL_MAE_DELTA:
            verdict = VERDICT_INVERTED
        else:
            verdict = VERDICT_FLAT

    narrative, recommendations = _message(
        verdict, from_tier, to_tier, improvement
    )
    total = sum(bucket["outcome_count"] for bucket in buckets)
    return {
        "user_id": user_id,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "total_outcomes": total,
        "discarded_rows": discarded,
        "populated_tier_count": len(populated),
        "verdict": verdict,
        "comparison_from_tier": from_tier,
        "comparison_to_tier": to_tier,
        "absolute_error_improvement": improvement,
        "relative_error_reduction": relative_reduction,
        "buckets": buckets,
        "narrative": narrative,
        "recommendations": recommendations,
    }


__all__ = [
    "VERDICT_ALIGNED",
    "VERDICT_INVERTED",
    "VERDICT_FLAT",
    "VERDICT_INSUFFICIENT",
    "TIER_ORDER",
    "MIN_OUTCOMES_PER_TIER",
    "MIN_MEANINGFUL_MAE_DELTA",
    "build_signal_quality_accuracy",
]
