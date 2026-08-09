"""
Pure post-launch revenue trajectory forecast for outcome-tracker data.

The ``outcome_tracker`` table lets founders log lightweight checkpoints over
time (week 1, week 4, ...), each carrying an optional ``actual_revenue`` and
``predicted_revenue`` alongside the conversion signal. The conversion
forecast module answers "where is conversion heading?"; this module answers
the revenue question the timeline cannot: **where is revenue heading, and
is the project on track versus the simulation's predicted revenue?**

Logic (deliberately deterministic and conservative — no DB, no LLM):

* Checkpoints with a usable ``actual_revenue`` and ``recorded_at`` are
  sorted by time and converted to days-since-first-point. Negative revenue
  is clamped to zero (a founder can log a refund week as 0, not a negative
  number).
* A simple linear trend is fitted to (days, revenue). The fitted slope
  drives 30/60/90-day projections anchored at the latest observed
  checkpoint. Because revenue has no natural 100% ceiling, projections are
  only capped by a saturation headroom above the simulation's predicted
  revenue (or 25% above the best observed checkpoint when no prediction
  exists).
* The verdict compares the 30-day projection (or the latest actual when it
  already meets the prediction) against the target:
  ``ABOVE_TARGET`` / ``ON_TRACK`` / ``BELOW_TARGET`` / ``STALLED`` /
  ``INSUFFICIENT_DATA``.
* ``days_to_target`` solves for when the trend line reaches the predicted
  revenue, capped at three years so a hopeless run doesn't surface a
  meaningless multi-decade estimate.
* Confidence is HIGH / MEDIUM / LOW based on checkpoint count, observation
  span, and fit quality (R²), matching the conversion forecast so a
  two-point trend is never presented with the same weight as a month of
  checkpoints.

The module is pure-Python (numpy arithmetic only) and tolerates malformed,
duplicate, or out-of-order rows so one bad checkpoint cannot crash the
forecast.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

# Minimum usable checkpoints before a forecast is attempted.
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

# A slope is FLAT when it stays below 0.5% of the best observed checkpoint
# per day (plus a tiny absolute epsilon so zero-revenue series are treated
# as flat rather than degenerate).
FLAT_SLOPE_FRACTION: float = 0.005
FLAT_SLOPE_ABS: float = 1e-9

# A projection within ±10% of the predicted revenue is ON_TRACK.
ON_TRACK_TOLERANCE: float = 0.10

# Saturation ceiling: 2% headroom above the prediction/observed max so the
# cap never sits exactly on an observed value, and 25% above the observed
# max when no prediction exists. Revenue has no hard upper bound, so the
# ceiling is derived from the best available anchor rather than a fixed 1.0.
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


def _safe_revenue(value: Any) -> float | None:
    """Coerce a revenue value to a non-negative finite float or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, parsed)


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
    """Extract sorted, deduplicated ``(days_since_first, revenue)`` pairs.

    Rows with a missing/unusable revenue or timestamp are dropped. Rows
    sharing the exact same timestamp keep the last one (the most recently
    logged checkpoint wins). Days are measured from the earliest usable
    checkpoint.
    """
    raw: list[tuple[float, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        revenue = _safe_revenue(row.get("actual_revenue"))
        ts = _timestamp_seconds(row.get("recorded_at"))
        if revenue is None or ts is None:
            continue
        raw.append((ts, revenue))
    if not raw:
        return []

    raw.sort(key=lambda pair: pair[0])
    deduped: list[tuple[float, float]] = []
    for ts, revenue in raw:
        if deduped and abs(deduped[-1][0] - ts) < 1e-9:
            deduped[-1] = (ts, revenue)
        else:
            deduped.append((ts, revenue))

    t0 = deduped[0][0]
    return [
        (round((ts - t0) / 86400.0, 6), revenue)
        for ts, revenue in deduped
    ]


def _linear_fit(
    points: list[tuple[float, float]],
) -> tuple[float, float | None]:
    """Fit ``y = slope * t + intercept``; return ``(slope, R²)``.

    Degenerate inputs (fewer than two distinct timestamps) yield a flat
    slope and ``None`` R² instead of NaN. A perfectly flat series (zero
    variance in revenue, real time spread) is a perfect fit, so it reports
    R² = 1.0 rather than an undefined value.
    """
    if len(points) < 2:
        return 0.0, None
    t = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    if float(np.var(t)) == 0.0:
        return 0.0, None
    if float(np.var(y)) == 0.0:
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


def _ceiling(target: float | None, max_observed: float) -> float | None:
    """Saturation cap for projections, or ``None`` when there is no anchor.

    With a target, cap at 2% headroom above the larger of the target and the
    best observed checkpoint. Without a target, cap at 25% above the best
    observed checkpoint when that checkpoint is positive; an all-zero series
    has no anchor, so no cap is applied (the projections stay at zero).
    """
    if target is not None:
        return round(max(target, max_observed) * CEILING_HEADROOM_FRACTION, 2)
    if max_observed > 0.0:
        return round(max_observed * OBSERVED_MAX_EXTENSION, 2)
    return None


def _projected(
    latest: float,
    slope: float,
    horizon_days: int,
    ceiling: float | None,
) -> float:
    raw = latest + slope * horizon_days
    if ceiling is not None:
        raw = min(ceiling, raw)
    return round(max(0.0, raw), 2)


def _is_flat_slope(slope: float, max_observed: float) -> bool:
    """Scale-relative flatness: below 0.5% of peak revenue per day."""
    return abs(slope) <= FLAT_SLOPE_ABS + max_observed * FLAT_SLOPE_FRACTION


def _trend_label(slope: float, max_observed: float) -> str:
    if slope > 0.0 and not _is_flat_slope(slope, max_observed):
        return TREND_CONVERGING
    if slope < 0.0 and not _is_flat_slope(slope, max_observed):
        return TREND_DECLINING
    return TREND_FLAT


def _verdict(
    target: float | None,
    latest: float,
    slope: float,
    max_observed: float,
    forecasts: list[dict[str, Any]],
) -> str:
    if target is None:
        return VERDICT_INSUFFICIENT_DATA
    if latest >= target:
        return VERDICT_ABOVE_TARGET
    if slope <= 0.0 or _is_flat_slope(slope, max_observed):
        return VERDICT_STALLED
    projected_30 = forecasts[0]["projected_revenue"]
    if projected_30 >= target * (1.0 + ON_TRACK_TOLERANCE):
        return VERDICT_ABOVE_TARGET
    if projected_30 >= target * (1.0 - ON_TRACK_TOLERANCE):
        return VERDICT_ON_TRACK
    return VERDICT_BELOW_TARGET


def _days_to_target(
    target: float | None,
    latest: float,
    slope: float,
    max_observed: float,
) -> float | None:
    if (
        target is None
        or latest >= target
        or slope <= 0.0
        or _is_flat_slope(slope, max_observed)
    ):
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


def _format_revenue(value: float) -> str:
    """Compact rupee-style formatting: ``₹1,250`` (no decimals)."""
    return f"₹{value:,.0f}"


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
            "Log at least 2 revenue checkpoints on different dates to "
            "unlock the revenue trajectory forecast."
        )
    span_text = f"{span_days:.0f} days"
    if target is None:
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_text}, "
            f"revenue is {_trend_phrase(trend)} at "
            f"{_format_revenue(latest)}. Add the project's predicted "
            "revenue (or run a simulation) to get an on-track verdict."
        )
    if verdict == VERDICT_ABOVE_TARGET:
        return (
            f"Latest actual revenue ({_format_revenue(latest)}) already "
            f"meets or exceeds the predicted {_format_revenue(target)} — "
            "trajectory is above target."
        )
    if verdict == VERDICT_STALLED:
        movement = (
            "has been falling"
            if trend == TREND_DECLINING
            else "has not improved"
        )
        return (
            f"Latest actual revenue ({_format_revenue(latest)}) {movement} "
            f"over {span_text} — stalled below the predicted "
            f"{_format_revenue(target)}."
        )
    if projected_30 is None:
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_text}, "
            f"revenue is {_trend_phrase(trend)} toward the predicted "
            f"{_format_revenue(target)}."
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
            f"revenue is trending toward the predicted "
            f"{_format_revenue(target)}; the model projects "
            f"{_format_revenue(projected_30)} in 30 days (on track)."
            f"{tail}"
        )
    return (
        f"Across {sample_count} checkpoint(s) spanning {span_text}, "
        f"revenue is projected to reach only {_format_revenue(projected_30)} "
        f"in 30 days versus the predicted {_format_revenue(target)} (slope "
        f"{_format_revenue(slope)}/day) — below target."
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
                "label": "latest_revenue",
                "value": latest,
                "severity": severity,
                "display": f"Latest revenue: {_format_revenue(latest)}",
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
                "display": f"Projected 30-day revenue: {_format_revenue(projected_30)}",
            }
        )

    if days_to_target is not None:
        signals.append(
            {
                "label": "days_to_target",
                "value": days_to_target,
                "severity": SIGNAL_OK,
                "display": f"Days to predicted revenue: ~{days_to_target:.0f}",
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


def build_outcome_tracker_revenue_forecast(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    predicted_revenue: float | None = None,
) -> dict[str, Any]:
    """Compose the post-launch revenue trajectory forecast.

    Args:
        rows: list of outcome_tracker row dicts. Each row must expose
            ``actual_revenue`` and ``recorded_at`` (datetime or ISO string);
            extra fields are ignored.
        project_id: owning project id (echoed back).
        predicted_revenue: the simulation's predicted revenue (``None`` /
            ``<= 0`` means no target).

    Returns:
        Dict matching :class:`OutcomeTrackerRevenueForecastOut` (see the
        schema module).
    """
    points = _usable_points(rows)
    sample_count = len(points)
    latest = points[-1][1] if points else None
    target = _safe_revenue(predicted_revenue)
    if target is not None and target <= 0.0:
        target = None

    if sample_count < MIN_POINTS:
        return {
            "project_id": project_id,
            "sample_count": sample_count,
            "span_days": None,
            "latest_revenue": latest,
            "predicted_revenue": target,
            "ceiling_revenue": None,
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
    trend = _trend_label(slope, max_observed)
    forecasts = [
        {
            "horizon_days": horizon,
            "projected_revenue": _projected(
                latest if latest is not None else 0.0,
                slope,
                horizon,
                ceiling,
            ),
        }
        for horizon in HORIZONS_DAYS
    ]
    verdict = _verdict(
        target,
        latest or 0.0,
        slope,
        max_observed,
        forecasts,
    )
    days_to_target = _days_to_target(
        target,
        latest or 0.0,
        slope,
        max_observed,
    )
    confidence = _confidence(sample_count, span_days, r2)

    return {
        "project_id": project_id,
        "sample_count": sample_count,
        "span_days": span_days,
        "latest_revenue": latest,
        "predicted_revenue": target,
        "ceiling_revenue": ceiling,
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
            projected_30=forecasts[0]["projected_revenue"],
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
            projected_30=forecasts[0]["projected_revenue"],
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
    "build_outcome_tracker_revenue_forecast",
]
