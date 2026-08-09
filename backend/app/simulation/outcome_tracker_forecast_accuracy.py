"""Historical verification of the conversion trajectory forecast.

The trajectory-forecast endpoint answers "where is conversion heading?"
from the founder's logged checkpoints. This module answers the follow-up
question every founder should ask before trusting that projection: **how
accurate have past forecasts actually been?**

The verification is out-of-sample and uses the exact same deterministic
arithmetic as the production forecast: for every checkpoint that has at
least :data:`MIN_POINTS` earlier checkpoints AND a later checkpoint at or
beyond a forecast horizon, we rebuild the forecast that the production
builder *would have* produced from that history and compare it to what
actually happened at the horizon. This includes the production saturation
ceiling, so a strongly rising series that the conservative ceiling capped
will honestly score as under-predicted rather than being re-forecast with
an idealized unlimited trend.

Per horizon (30/60/90 days) we aggregate:

* ``mean_abs_error`` / ``mean_abs_pct_error`` (MAPE, actual>0 only).
* ``bias`` — mean(forecast − actual); positive = over-predicted.
* ``bias_direction`` — OVER_PREDICTS / UNDER_PREDICTS / BALANCED /
  INSUFFICIENT_DATA using the same 2pp threshold as calibration.
* ``accuracy_score`` — mean per-check score in ``[0, 100]`` where 100 is a
  perfect projection (error relative to actual, floored at 1pp so a
  near-zero actual cannot produce an absurd score).
* ``within_2pp_rate`` — fraction of checks within ±2pp.

The module is pure-Python (numpy arithmetic only), tolerates malformed /
duplicate / out-of-order rows, and never touches the DB or LLM.
"""
from __future__ import annotations

from typing import Any

from app.simulation.outcome_tracker_forecast import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT_DATA,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    HORIZONS_DAYS,
    MIN_POINTS,
    _ceiling,
    _linear_fit,
    _projected,
    _safe_rate,
    _usable_points,
)

# Verdict labels.
VERDICT_ACCURATE: str = "ACCURATE"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_IMPRECISE: str = "IMPRECISE"
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Bias direction labels (same threshold convention as calibration).
BIAS_OVER_PREDICTS: str = "OVER_PREDICTS"
BIAS_UNDER_PREDICTS: str = "UNDER_PREDICTS"
BIAS_BALANCED: str = "BALANCED"
BIAS_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# A forecast is only verifiable once we have MIN_POINTS history points AND a
# later checkpoint at/after the horizon. Three checks is the floor for any
# verdict; confidence ramps at 5 and 10 checks.
MIN_VERIFICATIONS_LOW: int = 3
MIN_VERIFICATIONS_MEDIUM: int = 5
MIN_VERIFICATIONS_HIGH: int = 10

# Accuracy-score bands. 90+ = the model's projections have been near misses;
# 70–90 = usable but noisy; below 70 = materially off.
ACCURATE_MIN_SCORE: float = 90.0
MODERATE_MIN_SCORE: float = 70.0

# Same ±2pp threshold the calibration modules use; |bias| above this is a
# systematic over/under-prediction.
BIAS_THRESHOLD: float = 0.02

# A check within ±2pp of the realized value counts as a hit.
WITHIN_TOLERANCE: float = 0.02

# Floor for the accuracy denominator so a 0.0 actual can't produce an
# infinite/absurd error ratio.
MIN_RATE_DENOMINATOR: float = 0.01


def _bias_direction(bias: float) -> str:
    if bias > BIAS_THRESHOLD:
        return BIAS_OVER_PREDICTS
    if bias < -BIAS_THRESHOLD:
        return BIAS_UNDER_PREDICTS
    return BIAS_BALANCED


def _verify_horizon(
    points: list[tuple[float, float]],
    target: float | None,
    horizon_days: int,
) -> list[tuple[float, float]]:
    """Return ``(forecast, actual)`` pairs for one horizon.

    For each anchor checkpoint with at least ``MIN_POINTS`` history (itself
    included), the production trend fit is rebuilt from the anchor's history
    and projected ``horizon_days`` ahead. The actual value is the first
    checkpoint at or beyond that deadline. Both values are raw floats; the
    caller aggregates them.
    """
    checks: list[tuple[float, float]] = []
    next_actual_index = MIN_POINTS
    for anchor_index in range(MIN_POINTS - 1, len(points) - 1):
        if next_actual_index <= anchor_index:
            next_actual_index = anchor_index + 1
        deadline = points[anchor_index][0] + horizon_days
        while (
            next_actual_index < len(points)
            and points[next_actual_index][0] < deadline
        ):
            next_actual_index += 1
        if next_actual_index >= len(points):
            break

        history = points[: anchor_index + 1]
        latest = history[-1][1]
        max_observed = max(p[1] for p in history)
        ceiling = _ceiling(target, max_observed)
        slope, _r2 = _linear_fit(history)
        forecast = _projected(latest, slope, horizon_days, ceiling)
        actual = points[next_actual_index][1]
        checks.append((forecast, actual))
    return checks


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _aggregate_horizon(
    horizon_days: int,
    checks: list[tuple[float, float]],
) -> dict[str, Any]:
    """Summarize one horizon's ``(forecast, actual)`` checks."""
    base: dict[str, Any] = {
        "horizon_days": horizon_days,
        "sample_count": len(checks),
        "mean_abs_error": None,
        "mean_abs_pct_error": None,
        "bias": None,
        "bias_direction": BIAS_INSUFFICIENT_DATA,
        "accuracy_score": None,
        "within_2pp_rate": None,
    }
    if not checks:
        return base

    errors = [forecast - actual for forecast, actual in checks]
    abs_errors = [abs(error) for error in errors]
    mean_abs_error = sum(abs_errors) / len(abs_errors)

    pct_errors = [
        abs(error) / actual
        for error, (forecast, actual) in zip(errors, checks)
        if actual > 0.0
    ]
    mean_abs_pct_error = (
        sum(pct_errors) / len(pct_errors) if pct_errors else None
    )

    bias = sum(errors) / len(errors)
    accuracy = sum(
        max(
            0.0,
            1.0 - abs(error) / max(actual, MIN_RATE_DENOMINATOR),
        )
        * 100.0
        for error, (forecast, actual) in zip(errors, checks)
    ) / len(errors)
    within_2pp = sum(1.0 for ae in abs_errors if ae <= WITHIN_TOLERANCE) / len(
        abs_errors
    )

    base.update(
        {
            "mean_abs_error": _round_or_none(mean_abs_error),
            "mean_abs_pct_error": _round_or_none(mean_abs_pct_error),
            "bias": _round_or_none(bias),
            "bias_direction": _bias_direction(bias),
            "accuracy_score": round(accuracy, 2),
            "within_2pp_rate": round(within_2pp, 6),
        }
    )
    return base


def _overall_metrics(
    checks: list[tuple[float, float]],
) -> dict[str, Any]:
    """Flatten all horizon checks into one overall summary."""
    base: dict[str, Any] = {
        "overall_accuracy_score": None,
        "overall_mean_abs_error": None,
        "overall_bias": None,
        "overall_bias_direction": BIAS_INSUFFICIENT_DATA,
    }
    if not checks:
        return base
    errors = [forecast - actual for forecast, actual in checks]
    mean_abs_error = sum(abs(e) for e in errors) / len(errors)
    bias = sum(errors) / len(errors)
    accuracy = sum(
        max(
            0.0,
            1.0 - abs(error) / max(actual, MIN_RATE_DENOMINATOR),
        )
        * 100.0
        for error, (forecast, actual) in zip(errors, checks)
    ) / len(errors)
    return {
        "overall_accuracy_score": round(accuracy, 2),
        "overall_mean_abs_error": _round_or_none(mean_abs_error),
        "overall_bias": _round_or_none(bias),
        "overall_bias_direction": _bias_direction(bias),
    }


def _verdict(total_checks: int, overall_accuracy: float | None) -> str:
    if total_checks < MIN_VERIFICATIONS_LOW or overall_accuracy is None:
        return VERDICT_INSUFFICIENT_DATA
    if overall_accuracy >= ACCURATE_MIN_SCORE:
        return VERDICT_ACCURATE
    if overall_accuracy >= MODERATE_MIN_SCORE:
        return VERDICT_MODERATE
    return VERDICT_IMPRECISE


def _confidence(total_checks: int) -> str:
    if total_checks >= MIN_VERIFICATIONS_HIGH:
        return CONFIDENCE_HIGH
    if total_checks >= MIN_VERIFICATIONS_MEDIUM:
        return CONFIDENCE_MEDIUM
    if total_checks >= MIN_VERIFICATIONS_LOW:
        return CONFIDENCE_LOW
    return CONFIDENCE_INSUFFICIENT_DATA


def _narrative(
    total_checks: int,
    overall_accuracy: float | None,
    overall_mean_abs_error: float | None,
    overall_bias: float | None,
    bias_direction: str,
) -> str:
    if total_checks < MIN_VERIFICATIONS_LOW:
        return (
            "Keep logging conversion checkpoints over a 30+ day span to "
            "verify how accurate the trajectory forecast has been."
        )
    if bias_direction == BIAS_OVER_PREDICTS:
        bias_phrase = (
            f"over-predicted conversion by {overall_bias * 100:.2f}pp on average"
        )
    elif bias_direction == BIAS_UNDER_PREDICTS:
        bias_phrase = (
            f"under-predicted conversion by {abs(overall_bias) * 100:.2f}pp on average"
        )
    else:
        bias_phrase = "shown no systematic over- or under-prediction"
    error_text = (
        f" (average error {overall_mean_abs_error * 100:.2f}pp)"
        if overall_mean_abs_error is not None
        else ""
    )
    return (
        f"Across {total_checks} historical forecast checks, the 30/60/90-day "
        f"projections have been {overall_accuracy:.1f}% accurate{error_text}. "
        f"The model has {bias_phrase}."
    )


def build_outcome_tracker_forecast_accuracy(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    predicted_conversion_rate: float | None = None,
) -> dict[str, Any]:
    """Compose the historical forecast-accuracy verification.

    Args:
        rows: outcome_tracker row dicts (same shape as the trajectory
            forecast builder accepts).
        project_id: owning project id (echoed back).
        predicted_conversion_rate: the simulation's predicted conversion
            rate in ``[0, 1]``; used only for the same saturation ceiling
            the production forecast uses (``None`` / ``<= 0`` means no
            target, so the ceiling is observed-max based).

    Returns:
        Dict matching :class:`OutcomeTrackerForecastAccuracyOut`.
    """
    points = _usable_points(rows)
    target = _safe_rate(predicted_conversion_rate)
    if target is not None and target <= 0.0:
        target = None

    horizons: list[dict[str, Any]] = []
    all_checks: list[tuple[float, float]] = []
    for horizon_days in HORIZONS_DAYS:
        checks = _verify_horizon(points, target, horizon_days)
        all_checks.extend(checks)
        horizons.append(_aggregate_horizon(horizon_days, checks))

    total_checks = len(all_checks)
    overall = _overall_metrics(all_checks)
    verdict = _verdict(total_checks, overall["overall_accuracy_score"])
    confidence = _confidence(total_checks)

    return {
        "project_id": project_id,
        "total_verifications": total_checks,
        **overall,
        "overall_verdict": verdict,
        "confidence": confidence,
        "narrative": _narrative(
            total_checks,
            overall["overall_accuracy_score"],
            overall["overall_mean_abs_error"],
            overall["overall_bias"],
            overall["overall_bias_direction"],
        ),
        "horizons": horizons,
    }


__all__ = [
    "MIN_VERIFICATIONS_LOW",
    "MIN_VERIFICATIONS_MEDIUM",
    "MIN_VERIFICATIONS_HIGH",
    "VERDICT_ACCURATE",
    "VERDICT_MODERATE",
    "VERDICT_IMPRECISE",
    "VERDICT_INSUFFICIENT_DATA",
    "BIAS_OVER_PREDICTS",
    "BIAS_UNDER_PREDICTS",
    "BIAS_BALANCED",
    "BIAS_INSUFFICIENT_DATA",
    "build_outcome_tracker_forecast_accuracy",
]
