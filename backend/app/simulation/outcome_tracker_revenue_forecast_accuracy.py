"""Historical verification of the revenue trajectory forecast.

The revenue-forecast endpoint answers "where is revenue heading?" from the
founder's logged checkpoints. This module answers the follow-up question
every founder should ask before trusting that projection: **how accurate
have past revenue forecasts actually been?**

The verification is out-of-sample and uses the exact same deterministic
arithmetic as the production revenue forecast: for every checkpoint that
has at least :data:`MIN_POINTS` earlier checkpoints AND a later checkpoint
at or beyond a forecast horizon — but no more than half a horizon late, so
a sparse checkpoint months after the deadline cannot masquerade as the
horizon's realized value — we rebuild the forecast that the production
builder *would have* produced from that history and compare it to what
actually happened at the horizon. This includes the production saturation
ceiling, so a strongly rising series that the conservative ceiling capped
will honestly score as under-predicted rather than being re-forecast with
an idealized unlimited trend.

Per horizon (30/60/90 days) we aggregate:

* ``mean_abs_error`` / ``mean_abs_pct_error`` (MAPE, actual > 0 only).
* ``bias`` — mean(forecast − actual); positive = over-predicted.
* ``bias_direction`` — OVER_PREDICTS / UNDER_PREDICTS / BALANCED /
  INSUFFICIENT_DATA. A bias is material when it exceeds 10% of the average
  realized revenue (with a ₹100 floor) so a rounding-level miss on a
  zero-revenue project is not reported as a systematic error.
* ``accuracy_score`` — mean per-check score in ``[0, 100]`` where 100 is a
  perfect projection (error relative to actual, floored at ₹100 so a
  near-zero actual cannot produce an absurd score).
* ``within_tolerance_rate`` — fraction of checks within ±10% of the
  realized revenue (with a ₹100 absolute floor).

The module is pure-Python (numpy arithmetic only), tolerates malformed /
duplicate / out-of-order rows, and never touches the DB or LLM.
"""
from __future__ import annotations

from typing import Any

from app.simulation.outcome_tracker_revenue_forecast import (
    HORIZONS_DAYS,
    MIN_POINTS,
    _ceiling,
    _format_revenue,
    _linear_fit,
    _projected,
    _safe_revenue,
    _usable_points,
)

# Verdict labels.
VERDICT_ACCURATE: str = "ACCURATE"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_IMPRECISE: str = "IMPRECISE"
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Bias direction labels (same convention as the conversion verifier).
BIAS_OVER_PREDICTS: str = "OVER_PREDICTS"
BIAS_UNDER_PREDICTS: str = "UNDER_PREDICTS"
BIAS_BALANCED: str = "BALANCED"
BIAS_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# A forecast is only verifiable once we have MIN_POINTS history points AND
# a later checkpoint at/after the horizon. Three checks is the floor for
# any verdict; confidence ramps at 5 and 10 checks.
MIN_VERIFICATIONS_LOW: int = 3
MIN_VERIFICATIONS_MEDIUM: int = 5
MIN_VERIFICATIONS_HIGH: int = 10

# The shortest verifiable horizon is 30 days, so a history whose first and
# last checkpoints are closer than this cannot contain any horizon actual.
# Guidance below this span tells the founder to keep logging; above it, a
# lack of checks means the checkpoints themselves are too far apart.
MIN_VERIFY_SPAN_DAYS: float = 30.0

# The realized value for a horizon is the first checkpoint at/after the
# deadline, but only when it lands within this grace window. Without the
# bound, a 30-day forecast on a sparsely logged project would be judged
# against a checkpoint months later, silently conflating horizons and
# inflating errors. The window scales with the horizon (half a horizon
# late, with a small floor so short horizons stay meaningful).
VERIFY_GRACE_FRACTION: float = 0.5
VERIFY_GRACE_MIN_DAYS: float = 7.0

# Accuracy-score bands. 90+ = the model's projections have been near misses;
# 70–90 = usable but noisy; below 70 = materially off.
ACCURATE_MIN_SCORE: float = 90.0
MODERATE_MIN_SCORE: float = 70.0

# A bias is systematic only when it exceeds 10% of the average realized
# revenue, floored at ₹100 so near-zero series stay comparable.
BIAS_THRESHOLD_FRACTION: float = 0.10
BIAS_THRESHOLD_MIN: float = 100.0

# A check within ±10% of the realized revenue (floor ₹100) counts as a hit.
WITHIN_TOLERANCE_FRACTION: float = 0.10
WITHIN_TOLERANCE_MIN: float = 100.0

# Floor for the accuracy denominator so a 0.0 actual can't produce an
# infinite/absurd error ratio.
MIN_REVENUE_DENOMINATOR: float = 100.0


def _bias_direction(bias: float, mean_actual: float) -> str:
    """Classify a revenue bias against the realized scale of the checks."""
    threshold = max(mean_actual * BIAS_THRESHOLD_FRACTION, BIAS_THRESHOLD_MIN)
    if bias > threshold:
        return BIAS_OVER_PREDICTS
    if bias < -threshold:
        return BIAS_UNDER_PREDICTS
    return BIAS_BALANCED


def _verification_grace(horizon_days: int) -> float:
    """Max lateness (days) a checkpoint may have for a horizon's deadline."""
    return max(VERIFY_GRACE_MIN_DAYS, horizon_days * VERIFY_GRACE_FRACTION)


def _verify_horizon(
    points: list[tuple[float, float]],
    target: float | None,
    horizon_days: int,
) -> list[tuple[float, float]]:
    """Return ``(forecast, actual)`` revenue pairs for one horizon.

    For each anchor checkpoint with at least ``MIN_POINTS`` history (itself
    included), the production trend fit is rebuilt from the anchor's history
    and projected ``horizon_days`` ahead. The actual value is the first
    checkpoint at or beyond that deadline, provided it is no more than
    :func:`_verification_grace` days late — otherwise the checkpoint
    describes a materially different time window and the anchor is skipped.
    Both values are raw floats; the caller aggregates them.
    """
    checks: list[tuple[float, float]] = []
    next_actual_index = MIN_POINTS
    grace = _verification_grace(horizon_days)
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
        if points[next_actual_index][0] > deadline + grace:
            # The nearest later checkpoint is too far past the deadline to
            # measure this horizon; the next anchor may still use it.
            continue

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
    """Summarize one horizon's ``(forecast, actual)`` revenue checks."""
    base: dict[str, Any] = {
        "horizon_days": horizon_days,
        "sample_count": len(checks),
        "mean_abs_error": None,
        "mean_abs_pct_error": None,
        "bias": None,
        "bias_direction": BIAS_INSUFFICIENT_DATA,
        "accuracy_score": None,
        "within_tolerance_rate": None,
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
    mean_actual = sum(actual for _forecast, actual in checks) / len(checks)
    accuracy = sum(
        max(
            0.0,
            1.0 - abs(error) / max(actual, MIN_REVENUE_DENOMINATOR),
        )
        * 100.0
        for error, (forecast, actual) in zip(errors, checks)
    ) / len(errors)
    within_tolerance = sum(
        1.0
        for error, (forecast, actual) in zip(errors, checks)
        if abs(error) <= max(
            actual * WITHIN_TOLERANCE_FRACTION,
            WITHIN_TOLERANCE_MIN,
        )
    ) / len(checks)

    base.update(
        {
            "mean_abs_error": _round_or_none(mean_abs_error),
            "mean_abs_pct_error": _round_or_none(mean_abs_pct_error),
            "bias": _round_or_none(bias),
            "bias_direction": _bias_direction(bias, mean_actual),
            "accuracy_score": round(accuracy, 2),
            "within_tolerance_rate": round(within_tolerance, 6),
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
        "overall_mean_abs_pct_error": None,
        "overall_bias": None,
        "overall_bias_direction": BIAS_INSUFFICIENT_DATA,
    }
    if not checks:
        return base
    errors = [forecast - actual for forecast, actual in checks]
    mean_abs_error = sum(abs(e) for e in errors) / len(errors)
    pct_errors = [
        abs(e) / actual
        for e, (forecast, actual) in zip(errors, checks)
        if actual > 0.0
    ]
    mean_abs_pct_error = (
        sum(pct_errors) / len(pct_errors) if pct_errors else None
    )
    bias = sum(errors) / len(errors)
    mean_actual = sum(actual for _forecast, actual in checks) / len(checks)
    accuracy = sum(
        max(
            0.0,
            1.0 - abs(error) / max(actual, MIN_REVENUE_DENOMINATOR),
        )
        * 100.0
        for error, (forecast, actual) in zip(errors, checks)
    ) / len(errors)
    return {
        "overall_accuracy_score": round(accuracy, 2),
        "overall_mean_abs_error": _round_or_none(mean_abs_error),
        "overall_mean_abs_pct_error": _round_or_none(mean_abs_pct_error),
        "overall_bias": _round_or_none(bias),
        "overall_bias_direction": _bias_direction(bias, mean_actual),
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
        return "HIGH"
    if total_checks >= MIN_VERIFICATIONS_MEDIUM:
        return "MEDIUM"
    if total_checks >= MIN_VERIFICATIONS_LOW:
        return "LOW"
    return "INSUFFICIENT_DATA"


def _narrative(
    total_checks: int,
    overall_accuracy: float | None,
    overall_mean_abs_error: float | None,
    overall_mean_abs_pct_error: float | None,
    overall_bias: float | None,
    bias_direction: str,
    *,
    usable_points: int,
    span_days: float | None,
) -> str:
    if usable_points < MIN_POINTS:
        return (
            "Log at least 2 revenue checkpoints on different dates to "
            "unlock revenue-forecast verification."
        )
    if usable_points < MIN_POINTS + 1:
        # The earliest anchor needs two history points (itself included),
        # so exactly two checkpoints can never be verified.
        return (
            "Log at least 3 revenue checkpoints on different dates to "
            "unlock revenue-forecast verification."
        )
    if total_checks < MIN_VERIFICATIONS_LOW:
        if span_days is None or span_days < MIN_VERIFY_SPAN_DAYS:
            return (
                "Keep logging revenue checkpoints over a 30+ day span to "
                "verify how accurate the revenue trajectory forecast has been."
            )
        return (
            f"Your {usable_points} revenue checkpoints span "
            f"{span_days:.0f} days, but fewer than 3 line up with a later "
            "checkpoint inside the 30/60/90-day verification windows. Log "
            "checkpoints more frequently (ideally at least every 30 days) "
            "to unlock verification."
        )
    if bias_direction == BIAS_OVER_PREDICTS:
        bias_phrase = (
            f"over-predicted revenue by "
            f"{_format_revenue(overall_bias or 0.0)} on average"
        )
    elif bias_direction == BIAS_UNDER_PREDICTS:
        bias_phrase = (
            f"under-predicted revenue by "
            f"{_format_revenue(abs(overall_bias or 0.0))} on average"
        )
    else:
        bias_phrase = "shown no systematic over- or under-prediction"
    error_text = (
        f" (average error {_format_revenue(overall_mean_abs_error)})"
        if overall_mean_abs_error is not None
        else ""
    )
    pct_text = (
        f", {overall_mean_abs_pct_error * 100.0:.1f}% relative"
        if overall_mean_abs_pct_error is not None
        else ""
    )
    return (
        f"Across {total_checks} historical forecast checks, the 30/60/90-day "
        f"revenue projections have been {overall_accuracy:.1f}% accurate"
        f"{error_text}{pct_text}. The model has {bias_phrase}."
    )


def build_outcome_tracker_revenue_forecast_accuracy(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    predicted_revenue: float | None = None,
) -> dict[str, Any]:
    """Compose the historical revenue-forecast accuracy verification.

    Args:
        rows: outcome_tracker row dicts (same shape as the revenue forecast
            builder accepts, requiring ``actual_revenue`` and
            ``recorded_at``).
        project_id: owning project id (echoed back).
        predicted_revenue: the simulation's predicted revenue; used only for
            the same saturation ceiling the production forecast uses
            (``None`` / ``<= 0`` means no target, so the ceiling is
            observed-max based).

    Returns:
        Dict matching :class:`OutcomeTrackerRevenueForecastAccuracyOut`.
    """
    points = _usable_points(rows)
    usable_points = len(points)
    span_days = (
        round(points[-1][0] - points[0][0], 1) if usable_points >= 2 else None
    )
    target = _safe_revenue(predicted_revenue)
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
            overall["overall_mean_abs_pct_error"],
            overall["overall_bias"],
            overall["overall_bias_direction"],
            usable_points=usable_points,
            span_days=span_days,
        ),
        "horizons": horizons,
    }


__all__ = [
    "MIN_VERIFICATIONS_LOW",
    "MIN_VERIFICATIONS_MEDIUM",
    "MIN_VERIFICATIONS_HIGH",
    "MIN_VERIFY_SPAN_DAYS",
    "VERDICT_ACCURATE",
    "VERDICT_MODERATE",
    "VERDICT_IMPRECISE",
    "VERDICT_INSUFFICIENT_DATA",
    "BIAS_OVER_PREDICTS",
    "BIAS_UNDER_PREDICTS",
    "BIAS_BALANCED",
    "BIAS_INSUFFICIENT_DATA",
    "build_outcome_tracker_revenue_forecast_accuracy",
]
