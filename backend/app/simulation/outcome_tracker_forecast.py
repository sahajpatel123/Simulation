"""
Pure post-launch conversion trajectory forecast for outcome-tracker data.

The ``outcome_tracker`` table lets founders log lightweight conversion
checkpoints over time (week 1, week 4, ...). The existing timeline endpoint
shows where conversion *has been*; this module answers the forward-looking
question the timeline cannot: **where is conversion heading, and is the
project on track versus the simulation's prediction?**

Logic (deliberately deterministic and conservative — no DB, no LLM):

* Checkpoints with a usable ``actual_conversion_rate`` and ``recorded_at``
  are sorted by time and converted to days-since-first-point.
* A simple linear trend is fitted to (days, conversion). The fitted slope
  drives a 30/60/90-day projection anchored at the latest observed
  checkpoint and capped at a saturation ceiling (the simulation's predicted
  conversion, or 25% above the best observed checkpoint when no prediction
  exists — never above 100%).
* The verdict compares the 30-day projection (or the latest actual when it
  already meets the prediction) against the target:
  ``ABOVE_TARGET`` / ``ON_TRACK`` / ``BELOW_TARGET`` / ``STALLED`` /
  ``INSUFFICIENT_DATA``.
* ``days_to_target`` solves for when the trend line reaches the predicted
  conversion, capped at three years so a hopeless run doesn't surface a
  meaningless multi-decade estimate.
* Confidence is HIGH / MEDIUM / LOW based on checkpoint count, observation
  span, and fit quality (R²), so a two-point trend is never presented with
  the same weight as a month of checkpoints.

The module is pure-Python (numpy arithmetic only) and tolerates malformed,
duplicate, or out-of-order rows so one bad checkpoint cannot crash the
forecast.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

# Minimum usable checkpoints before a forecast is attempted. A single
# checkpoint only tells us where conversion is *now*, not where it is going.
MIN_POINTS: int = 2

# Confidence bands (checkpoint count / observation span / R²).
HIGH_CONFIDENCE_POINTS: int = 4
HIGH_CONFIDENCE_SPAN_DAYS: float = 14.0
HIGH_CONFIDENCE_MIN_R2: float = 0.50
MEDIUM_CONFIDENCE_POINTS: int = 3
MEDIUM_CONFIDENCE_SPAN_DAYS: float = 7.0
MEDIUM_CONFIDENCE_MIN_R2: float = 0.20

# Forecast horizons (days from the latest checkpoint).
HORIZONS_DAYS: tuple[int, int, int] = (30, 60, 90)

# Slopes with |slope| below this (per day, fraction) count as FLAT.
FLAT_SLOPE_ABS: float = 0.0002

# A projection within ±10% of the predicted conversion is ON_TRACK.
ON_TRACK_TOLERANCE: float = 0.10

# Saturation ceiling: 2% headroom above the prediction/observed max so the
# cap never sits exactly on an observed value, and 25% above the observed
# max when no prediction exists.
CEILING_HEADROOM_FRACTION: float = 1.02
OBSERVED_MAX_EXTENSION: float = 1.25

# Forecasts beyond three years are reported as None (no meaningful target
# date) rather than a silly huge number.
MAX_DAYS_TO_TARGET: float = 1095.0

# Trend labels.
TREND_CONVERGING: str = "CONVERGING"
TREND_FLAT: str = "FLAT"
TREND_DECLINING: str = "DECLINING"
TREND_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Verdict labels.
VERDICT_ABOVE_TARGET: str = "ABOVE_TARGET"
VERDICT_ON_TRACK: str = "ON_TRACK"
VERDICT_BELOW_TARGET: str = "BELOW_TARGET"
VERDICT_STALLED: str = "STALLED"
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Confidence labels.
CONFIDENCE_HIGH: str = "HIGH"
CONFIDENCE_MEDIUM: str = "MEDIUM"
CONFIDENCE_LOW: str = "LOW"
CONFIDENCE_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Signal severity buckets — same convention as the other digest modules.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_rate(value: Any) -> float | None:
    """Coerce a conversion rate to ``[0, 1]`` or ``None`` when unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def _timestamp_seconds(value: Any) -> float | None:
    """Coerce a recorded_at value to epoch seconds (UTC) or ``None``."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    try:
        return dt.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _usable_points(
    rows: list[dict[str, Any]] | None,
) -> list[tuple[float, float]]:
    """Extract sorted, deduplicated ``(days_since_first, rate)`` pairs.

    Rows with a missing/unusable rate or timestamp are dropped. Rows sharing
    the exact same timestamp keep the last one (the most recently logged
    checkpoint wins). Days are measured from the earliest usable checkpoint.
    """
    raw: list[tuple[float, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        rate = _safe_rate(row.get("actual_conversion_rate"))
        ts = _timestamp_seconds(row.get("recorded_at"))
        if rate is None or ts is None:
            continue
        raw.append((ts, rate))
    if not raw:
        return []

    raw.sort(key=lambda pair: pair[0])
    deduped: list[tuple[float, float]] = []
    for ts, rate in raw:
        if deduped and abs(deduped[-1][0] - ts) < 1e-9:
            deduped[-1] = (ts, rate)
        else:
            deduped.append((ts, rate))

    t0 = deduped[0][0]
    return [
        (round((ts - t0) / 86400.0, 6), rate)
        for ts, rate in deduped
    ]


def _linear_fit(
    points: list[tuple[float, float]],
) -> tuple[float, float | None]:
    """Fit ``y = slope * t + intercept``; return ``(slope, R²)``.

    Degenerate inputs (fewer than two distinct timestamps) yield a flat
    slope and ``None`` R² instead of NaN. A perfectly flat series (zero
    variance in conversion, real time spread) is a perfect fit, so it
    reports R² = 1.0 rather than an undefined value.
    """
    if len(points) < 2:
        return 0.0, None
    t = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    if float(np.var(t)) == 0.0:
        return 0.0, None
    if float(np.var(y)) == 0.0:
        # The fitted line is exactly the constant conversion with zero
        # residual error, so R² is 1.0 (perfect-fit convention).
        return 0.0, 1.0
    try:
        slope, intercept = np.polyfit(t, y, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0.0, None
    if not math.isfinite(float(slope)):
        return 0.0, None

    predicted = slope * t + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2: float | None = None
    if ss_tot > 0.0:
        candidate = 1.0 - ss_res / ss_tot
        if math.isfinite(candidate):
            r2 = round(candidate, 6)
    return round(float(slope), 6), r2


def _ceiling(target: float | None, max_observed: float) -> float:
    """Saturation cap for projections, clamped to ``[max_observed, 1]``."""
    if target is not None:
        base = max(target, max_observed)
        ceiling = min(1.0, base * CEILING_HEADROOM_FRACTION)
    elif max_observed > 0.0:
        ceiling = min(1.0, max_observed * OBSERVED_MAX_EXTENSION)
    else:
        ceiling = 1.0
    ceiling = max(ceiling, max_observed)
    return round(max(0.0, min(1.0, ceiling)), 6)


def _projected(
    latest: float,
    slope: float,
    horizon_days: int,
    ceiling: float,
) -> float:
    raw = latest + slope * horizon_days
    return round(max(0.0, min(ceiling, raw)), 6)


def _trend_label(slope: float) -> str:
    if slope > FLAT_SLOPE_ABS:
        return TREND_CONVERGING
    if slope < -FLAT_SLOPE_ABS:
        return TREND_DECLINING
    return TREND_FLAT


def _verdict(
    target: float | None,
    latest: float,
    slope: float,
    forecasts: list[dict[str, Any]],
) -> str:
    if target is None:
        return VERDICT_INSUFFICIENT_DATA
    if latest >= target:
        return VERDICT_ABOVE_TARGET
    if slope <= 0.0:
        return VERDICT_STALLED
    projected_30 = forecasts[0]["projected_conversion_rate"]
    if projected_30 >= target * (1.0 + ON_TRACK_TOLERANCE):
        return VERDICT_ABOVE_TARGET
    if projected_30 >= target * (1.0 - ON_TRACK_TOLERANCE):
        return VERDICT_ON_TRACK
    return VERDICT_BELOW_TARGET


def _days_to_target(
    target: float | None,
    latest: float,
    slope: float,
) -> float | None:
    if target is None or latest >= target or slope <= 0.0:
        return None
    days = (target - latest) / slope
    if days > MAX_DAYS_TO_TARGET:
        return None
    return round(days, 1)


def _confidence(
    sample_count: int,
    span_days: float,
    r2: float | None,
) -> str:
    if sample_count < MIN_POINTS:
        return CONFIDENCE_INSUFFICIENT_DATA
    if (
        sample_count >= HIGH_CONFIDENCE_POINTS
        and span_days >= HIGH_CONFIDENCE_SPAN_DAYS
        and r2 is not None
        and r2 >= HIGH_CONFIDENCE_MIN_R2
    ):
        return CONFIDENCE_HIGH
    if (
        sample_count >= MEDIUM_CONFIDENCE_POINTS
        and span_days >= MEDIUM_CONFIDENCE_SPAN_DAYS
        and r2 is not None
        and r2 >= MEDIUM_CONFIDENCE_MIN_R2
    ):
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _trend_phrase(trend: str) -> str:
    if trend == TREND_CONVERGING:
        return "rising"
    if trend == TREND_DECLINING:
        return "falling"
    return "flat"


def _narrative(
    *,
    sample_count: int,
    span_days: float,
    latest: float,
    target: float | None,
    trend: str,
    slope: float,
    projected_30: float | None,
    days_to_target: float | None,
    verdict: str,
    confidence: str,
) -> str:
    if sample_count < MIN_POINTS:
        return (
            "Log at least 2 conversion checkpoints on different dates to "
            "unlock the trajectory forecast."
        )
    span_text = f"{span_days:.0f} days"
    if target is None:
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_text}, "
            f"conversion is {_trend_phrase(trend)} at {latest:.1%}. Add the "
            "project's predicted conversion (or run a simulation) to get an "
            "on-track verdict."
        )
    if verdict == VERDICT_ABOVE_TARGET:
        return (
            f"Latest actual conversion ({latest:.1%}) already meets or "
            f"exceeds the predicted {target:.1%} — trajectory is above target."
        )
    if verdict == VERDICT_STALLED:
        movement = (
            "has been falling"
            if trend == TREND_DECLINING
            else "has not improved"
        )
        return (
            f"Latest actual conversion ({latest:.1%}) {movement} over "
            f"{span_text} — stalled below the predicted {target:.1%}."
        )
    if projected_30 is None:
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_text}, "
            f"conversion is {_trend_phrase(trend)} toward the predicted "
            f"{target:.1%}."
        )
    if verdict == VERDICT_ON_TRACK:
        tail = ""
        if days_to_target is not None:
            unit = "day" if days_to_target == 1 else "days"
            tail = (
                f" Expected to reach the prediction in "
                f"~{days_to_target:.0f} {unit}."
            )
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_text}, "
            f"conversion is trending toward the predicted {target:.1%}; the "
            f"model projects {projected_30:.1%} in 30 days (on track)."
            f"{tail}"
        )
    return (
        f"Across {sample_count} checkpoint(s) spanning {span_text}, "
        f"conversion is projected to reach only {projected_30:.1%} in 30 "
        f"days versus the predicted {target:.1%} (slope {slope * 100:.3f}pp/"
        "day) — below target."
    )


def _severity_for_verdict(verdict: str) -> str:
    if verdict == VERDICT_ABOVE_TARGET or verdict == VERDICT_ON_TRACK:
        return SIGNAL_OK
    if verdict == VERDICT_STALLED:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def _key_signals(
    *,
    latest: float | None,
    target: float | None,
    trend: str,
    verdict: str,
    confidence: str,
    projected_30: float | None,
    days_to_target: float | None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []

    if latest is not None:
        if target is None:
            severity = SIGNAL_WATCH
        elif latest >= target:
            severity = SIGNAL_OK
        elif latest >= target * (1.0 - ON_TRACK_TOLERANCE):
            severity = SIGNAL_WATCH
        else:
            severity = SIGNAL_CRITICAL
        signals.append(
            {
                "label": "latest_actual",
                "value": latest,
                "severity": severity,
                "display": f"Latest conversion: {latest:.2%}",
            }
        )

    if trend != TREND_INSUFFICIENT_DATA:
        signals.append(
            {
                "label": "trend",
                "value": trend,
                "severity": (
                    SIGNAL_OK
                    if trend == TREND_CONVERGING
                    else SIGNAL_WATCH
                    if trend == TREND_FLAT
                    else SIGNAL_CRITICAL
                ),
                "display": f"Trajectory: {trend.lower()}",
            }
        )

    if projected_30 is not None:
        signals.append(
            {
                "label": "forecast_30d",
                "value": projected_30,
                "severity": _severity_for_verdict(verdict),
                "display": f"Projected 30-day conversion: {projected_30:.2%}",
            }
        )

    if days_to_target is not None:
        signals.append(
            {
                "label": "days_to_target",
                "value": days_to_target,
                "severity": SIGNAL_OK,
                "display": f"Days to predicted conversion: ~{days_to_target:.0f}",
            }
        )

    signals.append(
        {
            "label": "confidence",
            "value": confidence,
            "severity": SIGNAL_OK if confidence == CONFIDENCE_HIGH else SIGNAL_WATCH,
            "display": f"Forecast confidence: {confidence.lower()}",
        }
    )
    return signals


def build_outcome_tracker_forecast(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    predicted_conversion_rate: float | None = None,
) -> dict[str, Any]:
    """Compose the post-launch conversion trajectory forecast.

    Args:
        rows: list of outcome_tracker row dicts. Each row must expose
            ``actual_conversion_rate`` and ``recorded_at`` (datetime or ISO
            string); extra fields are ignored.
        project_id: owning project id (echoed back).
        predicted_conversion_rate: the simulation's predicted conversion
            rate in ``[0, 1]`` (``None`` / ``<= 0`` means no target).

    Returns:
        Dict matching :class:`OutcomeTrackerForecastOut` (see the schema
        module).
    """
    points = _usable_points(rows)
    sample_count = len(points)
    latest = points[-1][1] if points else None
    target = _safe_rate(predicted_conversion_rate)
    if target is not None and target <= 0.0:
        target = None

    if sample_count < MIN_POINTS:
        return {
            "project_id": project_id,
            "sample_count": sample_count,
            "span_days": None,
            "latest_actual": latest,
            "predicted_conversion_rate": target,
            "ceiling_conversion_rate": None,
            "slope_per_day": None,
            "r_squared": None,
            "trend_label": TREND_INSUFFICIENT_DATA,
            "confidence": CONFIDENCE_INSUFFICIENT_DATA,
            "verdict": VERDICT_INSUFFICIENT_DATA,
            "forecasts": [],
            "days_to_target": None,
            "narrative": _narrative(
                sample_count=sample_count,
                span_days=0.0,
                latest=latest or 0.0,
                target=target,
                trend=TREND_INSUFFICIENT_DATA,
                slope=0.0,
                projected_30=None,
                days_to_target=None,
                verdict=VERDICT_INSUFFICIENT_DATA,
                confidence=CONFIDENCE_INSUFFICIENT_DATA,
            ),
            "key_signals": [],
        }

    span_days = round(points[-1][0] - points[0][0], 1)
    max_observed = max(p[1] for p in points)
    ceiling = _ceiling(target, max_observed)
    slope, r2 = _linear_fit(points)
    trend = _trend_label(slope)
    forecasts = [
        {
            "horizon_days": horizon,
            "projected_conversion_rate": _projected(
                latest if latest is not None else 0.0,
                slope,
                horizon,
                ceiling,
            ),
        }
        for horizon in HORIZONS_DAYS
    ]
    verdict = _verdict(target, latest or 0.0, slope, forecasts)
    days_to_target = _days_to_target(target, latest or 0.0, slope)
    confidence = _confidence(sample_count, span_days, r2)

    return {
        "project_id": project_id,
        "sample_count": sample_count,
        "span_days": span_days,
        "latest_actual": latest,
        "predicted_conversion_rate": target,
        "ceiling_conversion_rate": ceiling,
        "slope_per_day": slope,
        "r_squared": r2,
        "trend_label": trend,
        "confidence": confidence,
        "verdict": verdict,
        "forecasts": forecasts,
        "days_to_target": days_to_target,
        "narrative": _narrative(
            sample_count=sample_count,
            span_days=span_days,
            latest=latest or 0.0,
            target=target,
            trend=trend,
            slope=slope,
            projected_30=forecasts[0]["projected_conversion_rate"],
            days_to_target=days_to_target,
            verdict=verdict,
            confidence=confidence,
        ),
        "key_signals": _key_signals(
            latest=latest,
            target=target,
            trend=trend,
            verdict=verdict,
            confidence=confidence,
            projected_30=forecasts[0]["projected_conversion_rate"],
            days_to_target=days_to_target,
        ),
    }


__all__ = [
    "MIN_POINTS",
    "TREND_CONVERGING",
    "TREND_FLAT",
    "TREND_DECLINING",
    "TREND_INSUFFICIENT_DATA",
    "VERDICT_ABOVE_TARGET",
    "VERDICT_ON_TRACK",
    "VERDICT_BELOW_TARGET",
    "VERDICT_STALLED",
    "VERDICT_INSUFFICIENT_DATA",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_INSUFFICIENT_DATA",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_outcome_tracker_forecast",
]
