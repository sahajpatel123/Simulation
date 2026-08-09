"""Post-launch conversion tracking-drift early warning.

The trajectory forecast answers "where is conversion heading?" and the
forecast-accuracy endpoint answers "how accurate have past projections
been?". This module answers the real-time question neither one covers:
**is the project actually tracking the path the model expects, and is any
gap getting wider?**

For every checkpoint with enough history (:data:`MIN_POINTS` earlier
points), the production trend fit is rebuilt exactly the way the forecast
builder would, projected forward to the *next* checkpoint's observation
date, and compared with the conversion actually logged there. Signed
deviations (expected minus actual) are aggregated into a tracking error in
percentage points:

* mean error above +2pp  → actual conversion is running BEHIND the model's path;
* mean error below −2pp  → actual conversion is running AHEAD of it;
* otherwise              → ON_TRACK.

The sequence of deviations is then fitted to detect whether the gap is
widening, narrowing, or stable — the early-warning signal. Behind-and-
widening is the critical case (the forecast is optimistic and getting more
so); ahead-and-widening suggests the simulation under-predicts demand.

The module is pure-Python (numpy arithmetic only), shares the production
forecast's exact deterministic arithmetic (including the saturation
ceiling), and tolerates malformed / duplicate / out-of-order rows.
"""
from __future__ import annotations

from typing import Any

from app.simulation.outcome_tracker_forecast import (
    MIN_POINTS,
    SIGNAL_CRITICAL,
    SIGNAL_OK,
    SIGNAL_WATCH,
    _ceiling,
    _linear_fit,
    _projected,
    _safe_rate,
    _usable_points,
)

# Tracking-status labels.
TRACKING_ON_TRACK: str = "ON_TRACK"
TRACKING_AHEAD: str = "AHEAD"
TRACKING_BEHIND: str = "BEHIND"
TRACKING_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Drift-direction labels.
DRIFT_WIDENING: str = "WIDENING"
DRIFT_NARROWING: str = "NARROWING"
DRIFT_STABLE: str = "STABLE"
DRIFT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Same ±2pp band the calibration modules use: a mean deviation above this
# is a real tracking gap rather than checkpoint noise.
TRACKING_TOLERANCE: float = 0.02

# Drift direction needs at least three tracked steps (4+ checkpoints).
MIN_DRIFT_CHECKS: int = 3

# A gap slope below 0.5pp per tracked checkpoint counts as stable.
DRIFT_FLAT_SLOPE_PP_PER_CHECK: float = 0.5

# Keep the per-check history bounded so the payload stays small.
MAX_CHECKS_IN_HISTORY: int = 12


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _tracking_checks(
    points: list[tuple[float, float]],
    target: float | None,
) -> list[dict[str, Any]]:
    """Build ``(expected, actual, deviation)`` checks at each logged step.

    For every anchor checkpoint that has ``MIN_POINTS`` history, the trend
    fit is rebuilt from that history and projected forward to the next
    checkpoint's date using the same arithmetic (and saturation ceiling) as
    the production forecast. The signed deviation is ``expected - actual``.
    """
    checks: list[dict[str, Any]] = []
    for anchor in range(MIN_POINTS - 1, len(points) - 1):
        delta_days = points[anchor + 1][0] - points[anchor][0]
        if delta_days <= 0.0:
            # Duplicate timestamps collapse to one usable point; a non-positive
            # gap cannot measure forward progress.
            continue
        history = points[: anchor + 1]
        latest = history[-1][1]
        max_observed = max(p[1] for p in history)
        ceiling = _ceiling(target, max_observed)
        slope, _r2 = _linear_fit(history)
        expected = _projected(latest, slope, delta_days, ceiling)
        actual = points[anchor + 1][1]
        checks.append(
            {
                "expected_conversion_rate": expected,
                "actual_conversion_rate": round(actual, 6),
                "deviation": round(expected - actual, 6),
                "days_since_first": round(points[anchor + 1][0], 1),
                "gap_days": round(delta_days, 1),
            }
        )
    return checks


def _tracking_status(mean_deviation: float | None) -> str:
    if mean_deviation is None:
        return TRACKING_INSUFFICIENT_DATA
    if mean_deviation > TRACKING_TOLERANCE:
        return TRACKING_BEHIND
    if mean_deviation < -TRACKING_TOLERANCE:
        return TRACKING_AHEAD
    return TRACKING_ON_TRACK


def _drift_direction(
    mean_deviation: float | None,
    slope_pp_per_check: float | None,
) -> str:
    if mean_deviation is None or slope_pp_per_check is None:
        return DRIFT_INSUFFICIENT_DATA
    if abs(slope_pp_per_check) <= DRIFT_FLAT_SLOPE_PP_PER_CHECK:
        return DRIFT_STABLE
    if mean_deviation > TRACKING_TOLERANCE:
        return DRIFT_WIDENING if slope_pp_per_check > 0.0 else DRIFT_NARROWING
    if mean_deviation < -TRACKING_TOLERANCE:
        return DRIFT_WIDENING if slope_pp_per_check < 0.0 else DRIFT_NARROWING
    return DRIFT_STABLE


def _severity(status: str, direction: str) -> str:
    if status == TRACKING_ON_TRACK:
        return SIGNAL_OK
    if status == TRACKING_BEHIND and direction == DRIFT_WIDENING:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def _narrative(
    *,
    sample_count: int,
    mean_error_pp: float | None,
    status: str,
    direction: str,
    slope_pp: float | None,
) -> str:
    if sample_count < 1 or mean_error_pp is None:
        return (
            "Log at least 2 conversion checkpoints on different dates to "
            "unlock tracking-drift alerts."
        )
    if status == TRACKING_ON_TRACK:
        return (
            f"Across {sample_count} tracked checkpoint step(s), actual "
            f"conversion has stayed within ±{TRACKING_TOLERANCE * 100:.0f}pp "
            f"of the model's expected path (mean error {mean_error_pp:+.2f}pp). "
            "No drift signal."
        )
    if status == TRACKING_AHEAD:
        gap_phrase = (
            f"running {abs(mean_error_pp):.2f}pp above the model's expected path"
        )
    else:
        gap_phrase = (
            f"running {abs(mean_error_pp):.2f}pp below the model's expected path"
        )
    if direction == DRIFT_INSUFFICIENT_DATA:
        return (
            f"Across {sample_count} tracked checkpoint step(s), actual "
            f"conversion is {gap_phrase}. Log 2 more checkpoints to see "
            "whether the gap is widening or closing."
        )
    if direction == DRIFT_WIDENING:
        tail = (
            " — the simulation may be under-predicting demand."
            if status == TRACKING_AHEAD
            else " — treat the current trajectory forecast as optimistic."
        )
        return (
            f"Across {sample_count} tracked checkpoint step(s), actual "
            f"conversion is {gap_phrase} and the gap is widening "
            f"({slope_pp:.2f}pp per checkpoint).{tail}"
        )
    if direction == DRIFT_NARROWING:
        return (
            f"Across {sample_count} tracked checkpoint step(s), actual "
            f"conversion is {gap_phrase}, but the gap is closing "
            f"({slope_pp:.2f}pp per checkpoint)."
        )
    return (
        f"Across {sample_count} tracked checkpoint step(s), actual "
        f"conversion is {gap_phrase} with the gap holding steady."
    )


def build_outcome_tracker_drift(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    predicted_conversion_rate: float | None = None,
) -> dict[str, Any]:
    """Compose the tracking-drift early-warning payload.

    Args:
        rows: outcome_tracker row dicts (same shape as the trajectory
            forecast builder accepts).
        project_id: owning project id (echoed back).
        predicted_conversion_rate: the simulation's predicted conversion
            rate in ``[0, 1]``; used only for the same saturation ceiling
            the production forecast uses (``None`` / ``<= 0`` means no
            target, so the ceiling is observed-max based).

    Returns:
        Dict matching :class:`OutcomeTrackerDriftOut`.
    """
    points = _usable_points(rows)
    target = _safe_rate(predicted_conversion_rate)
    if target is not None and target <= 0.0:
        target = None

    sample_count = len(points)
    span_days = (
        round(points[-1][0] - points[0][0], 1) if sample_count >= 2 else None
    )
    latest_actual = points[-1][1] if points else None
    checks = _tracking_checks(points, target)
    tracked_steps = len(checks)

    if tracked_steps < 1:
        return {
            "project_id": project_id,
            "sample_count": tracked_steps,
            "span_days": span_days,
            "latest_actual": latest_actual,
            "predicted_conversion_rate": target,
            "mean_tracking_error_pp": None,
            "mean_abs_tracking_error_pp": None,
            "latest_tracking_error_pp": None,
            "tracking_status": TRACKING_INSUFFICIENT_DATA,
            "gap_slope_pp_per_check": None,
            "drift_direction": DRIFT_INSUFFICIENT_DATA,
            "severity": SIGNAL_WATCH,
            "narrative": _narrative(
                sample_count=tracked_steps,
                mean_error_pp=None,
                status=TRACKING_INSUFFICIENT_DATA,
                direction=DRIFT_INSUFFICIENT_DATA,
                slope_pp=None,
            ),
            "checks": [],
        }

    deviations = [check["deviation"] for check in checks]
    mean_deviation = sum(deviations) / len(deviations)
    mean_error_pp = mean_deviation * 100.0
    mean_abs_error_pp = sum(abs(d) for d in deviations) / len(deviations) * 100.0
    latest_error_pp = deviations[-1] * 100.0

    slope_pp: float | None = None
    if tracked_steps >= MIN_DRIFT_CHECKS:
        slope, _r2 = _linear_fit(
            [(float(index), deviation) for index, deviation in enumerate(deviations)]
        )
        slope_pp = slope * 100.0

    status = _tracking_status(mean_deviation)
    direction = _drift_direction(mean_deviation, slope_pp)
    history = [
        {
            "expected_conversion_rate": check["expected_conversion_rate"],
            "actual_conversion_rate": check["actual_conversion_rate"],
            "deviation_pp": round(check["deviation"] * 100.0, 6),
            "days_since_first": check["days_since_first"],
            "gap_days": check["gap_days"],
        }
        for check in checks[-MAX_CHECKS_IN_HISTORY:]
    ]

    return {
        "project_id": project_id,
        "sample_count": tracked_steps,
        "span_days": span_days,
        "latest_actual": latest_actual,
        "predicted_conversion_rate": target,
        "mean_tracking_error_pp": _round_or_none(mean_error_pp),
        "mean_abs_tracking_error_pp": _round_or_none(mean_abs_error_pp),
        "latest_tracking_error_pp": _round_or_none(latest_error_pp),
        "tracking_status": status,
        "gap_slope_pp_per_check": _round_or_none(slope_pp),
        "drift_direction": direction,
        "severity": _severity(status, direction),
        "narrative": _narrative(
            sample_count=tracked_steps,
            mean_error_pp=mean_error_pp,
            status=status,
            direction=direction,
            slope_pp=slope_pp,
        ),
        "checks": history,
    }


__all__ = [
    "MIN_DRIFT_CHECKS",
    "DRIFT_WIDENING",
    "DRIFT_NARROWING",
    "DRIFT_STABLE",
    "DRIFT_INSUFFICIENT_DATA",
    "TRACKING_ON_TRACK",
    "TRACKING_AHEAD",
    "TRACKING_BEHIND",
    "TRACKING_INSUFFICIENT_DATA",
    "build_outcome_tracker_drift",
]
