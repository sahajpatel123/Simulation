"""
Pure post-launch goal-pacing evaluation for outcome-tracker data.

The trajectory-forecast endpoints answer "where is conversion / revenue
heading?"; this module answers the founder's planning question those
forecasts cannot: **will I hit my own conversion or revenue goal by a
specific deadline, and how much faster do I need to grow?**

Logic (deliberately deterministic and conservative - no DB, no LLM):

* Each requested metric (conversion rate and/or revenue) is read from the
  same outcome-tracker checkpoints. Usable values and timestamps are
  sorted, deduplicated, and converted to days-since-first-point.
* A linear trend is fitted to (days, value). The slope drives two numbers:
  the projected value at the founder's deadline and the days-to-goal at
  the current pace (capped at three years so a hopeless run does not
  surface a multi-decade estimate).
* When a deadline is supplied, the module reports whether the trend
  reaches the goal by then (``ALREADY_ACHIEVED`` / ``ON_TRACK`` /
  ``BEHIND`` / ``STALLED`` / ``EXPIRED``) and computes the pace actually
  required per day to hit the goal on time, so a founder can see exactly
  how much faster growth must be.
* Without a deadline the module still reports trend-based days-to-goal
  (``NO_DEADLINE``).
* Confidence is HIGH / MEDIUM / LOW based on checkpoint count, observation
  span, and fit quality (R²), matching the trajectory forecasts.

The module is pure-Python (numpy arithmetic only) and tolerates malformed,
duplicate, or out-of-order rows so one bad checkpoint cannot crash it.
Founder-supplied goals are sanitized the same way: non-finite, non-positive,
or boolean targets degrade to "no usable goal" instead of leaking NaN or
Infinity into the payload.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

import numpy as np

# Minimum usable checkpoints before a goal-pacing verdict is attempted.
MIN_POINTS: int = 2

# Confidence bands (checkpoint count / observation span / R²).
HIGH_CONFIDENCE_POINTS: int = 4
HIGH_CONFIDENCE_SPAN_DAYS: float = 14.0
HIGH_CONFIDENCE_MIN_R2: float = 0.50
MEDIUM_CONFIDENCE_POINTS: int = 3
MEDIUM_CONFIDENCE_SPAN_DAYS: float = 7.0
MEDIUM_CONFIDENCE_MIN_R2: float = 0.20

# Conversion slopes with |slope| below this (per day, fraction) are FLAT.
FLAT_SLOPE_ABS: float = 0.0002

# Revenue slopes are flat below 0.5% of the best observed checkpoint per
# day (plus a tiny absolute epsilon so zero-revenue series are flat).
FLAT_SLOPE_FRACTION: float = 0.005
FLAT_SLOPE_ABS_REVENUE: float = 1e-9

# Goal dates further out than three years are reported as None instead of
# a silly huge number.
MAX_DAYS_TO_TARGET: float = 1095.0

# Saturation ceiling: 2% headroom above the target/observed max so the cap
# never sits exactly on an observed value; 25% above the observed max when
# no target exists. Conversion is additionally clamped to 100%.
CEILING_HEADROOM_FRACTION: float = 1.02
OBSERVED_MAX_EXTENSION: float = 1.25

# Metric labels.
METRIC_CONVERSION: str = "conversion"
METRIC_REVENUE: str = "revenue"

# Trend labels.
TREND_CONVERGING: str = "CONVERGING"
TREND_FLAT: str = "FLAT"
TREND_DECLINING: str = "DECLINING"
TREND_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Status labels.
STATUS_ALREADY_ACHIEVED: str = "ALREADY_ACHIEVED"
STATUS_ON_TRACK: str = "ON_TRACK"
STATUS_BEHIND: str = "BEHIND"
STATUS_STALLED: str = "STALLED"
STATUS_EXPIRED: str = "EXPIRED"
STATUS_NO_DEADLINE: str = "NO_DEADLINE"
STATUS_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Confidence labels.
CONFIDENCE_HIGH: str = "HIGH"
CONFIDENCE_MEDIUM: str = "MEDIUM"
CONFIDENCE_LOW: str = "LOW"
CONFIDENCE_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Signal severity buckets - same convention as the other digest modules.
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


def _coerce_target(value: Any, *, revenue: bool) -> float | None:
    """Sanitize a founder goal to the value the pacing math actually uses.

    Conversion goals are clamped to ``[0, 1]`` and revenue goals to
    non-negative finite numbers. Non-finite, boolean, or non-positive goals
    return ``None`` so callers can treat them as "no usable goal" instead of
    letting NaN/Infinity flow into the response payload.
    """
    target = _safe_revenue(value) if revenue else _safe_rate(value)
    if target is not None and target <= 0.0:
        return None
    return target


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


def _usable_series(
    rows: list[dict[str, Any]] | None,
    *,
    revenue: bool,
) -> tuple[list[tuple[float, float]], float | None]:
    """Extract ``(days_since_first, value)`` points plus the latest timestamp.

    Rows with a missing/unusable value or timestamp are dropped. Rows
    sharing the exact same timestamp keep the last one (the most recently
    logged checkpoint wins). Days are measured from the earliest usable
    checkpoint.
    """
    raw: list[tuple[float, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = (
            _safe_revenue(row.get("actual_revenue"))
            if revenue
            else _safe_rate(row.get("actual_conversion_rate"))
        )
        ts = _timestamp_seconds(row.get("recorded_at"))
        if value is None or ts is None:
            continue
        raw.append((ts, value))
    if not raw:
        return [], None

    raw.sort(key=lambda pair: pair[0])
    deduped: list[tuple[float, float]] = []
    for ts, value in raw:
        if deduped and abs(deduped[-1][0] - ts) < 1e-9:
            deduped[-1] = (ts, value)
        else:
            deduped.append((ts, value))

    t0 = deduped[0][0]
    points = [
        (round((ts - t0) / 86400.0, 6), value)
        for ts, value in deduped
    ]
    return points, deduped[-1][0]


def _linear_fit(
    points: list[tuple[float, float]],
) -> tuple[float, float | None]:
    """Fit ``y = slope * t + intercept``; return ``(slope, R²)``.

    Degenerate inputs (fewer than two distinct timestamps) yield a flat
    slope and ``None`` R² instead of NaN. A perfectly flat series (zero
    variance in the metric, real time spread) is a perfect fit, so it
    reports R² = 1.0 rather than an undefined value.
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
        slope, _intercept = np.polyfit(t, y, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0.0, None
    if not math.isfinite(float(slope)):
        return 0.0, None

    predicted = slope * t + _intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2: float | None = None
    if ss_tot > 0.0:
        candidate = 1.0 - ss_res / ss_tot
        if math.isfinite(candidate):
            r2 = round(candidate, 6)
    return round(float(slope), 6), r2


def _is_flat_slope(
    slope: float,
    max_observed: float,
    *,
    revenue: bool,
) -> bool:
    """Scale-relative flatness for revenue; absolute flatness for conversion."""
    if revenue:
        return abs(slope) <= FLAT_SLOPE_ABS_REVENUE + max_observed * FLAT_SLOPE_FRACTION
    return abs(slope) <= FLAT_SLOPE_ABS


def _trend_label(
    slope: float,
    max_observed: float,
    *,
    revenue: bool,
) -> str:
    if slope > 0.0 and not _is_flat_slope(slope, max_observed, revenue=revenue):
        return TREND_CONVERGING
    if slope < 0.0 and not _is_flat_slope(slope, max_observed, revenue=revenue):
        return TREND_DECLINING
    return TREND_FLAT


def _ceiling(
    target: float | None,
    max_observed: float,
    *,
    revenue: bool,
) -> float | None:
    """Saturation cap for deadline projections."""
    if target is not None:
        ceiling = round(
            max(target, max_observed) * CEILING_HEADROOM_FRACTION,
            2,
        )
        if not revenue:
            ceiling = min(1.0, ceiling)
        return ceiling
    if max_observed > 0.0:
        ceiling = round(max_observed * OBSERVED_MAX_EXTENSION, 2)
        if not revenue:
            ceiling = min(1.0, ceiling)
        return ceiling
    if revenue:
        return None
    return 1.0


def _projected(
    latest: float,
    slope: float,
    horizon_days: float,
    ceiling: float | None,
    *,
    revenue: bool,
) -> float:
    raw = latest + slope * horizon_days
    if ceiling is not None:
        raw = min(ceiling, raw)
    raw = max(0.0, raw)
    return round(raw, 2 if revenue else 6)


def _days_to_target(
    target: float | None,
    latest: float,
    slope: float,
    max_observed: float,
    *,
    revenue: bool,
) -> float | None:
    if (
        target is None
        or latest >= target
        or slope <= 0.0
        or _is_flat_slope(slope, max_observed, revenue=revenue)
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


def _metric_label(revenue: bool) -> str:
    return METRIC_REVENUE if revenue else METRIC_CONVERSION


def _insufficient_narrative(*, revenue: bool, target: float | None) -> str:
    """Narrative for metrics with too little data or an unusable goal."""
    label = _metric_label(revenue)
    if target is None:
        return (
            f"Set a valid {label} goal (finite and greater than 0) to "
            "evaluate pacing toward it."
        )
    return (
        f"Log at least 2 {label} checkpoints on different dates to "
        f"evaluate pacing toward the {_fmt_value(target, revenue=revenue)} goal."
    )


def _fmt_rate(value: float) -> str:
    return f"{value:.2%}"


def _fmt_revenue(value: float, decimals: int = 0) -> str:
    return f"₹{value:,.{decimals}f}"


def _fmt_value(value: float, *, revenue: bool) -> str:
    return _fmt_revenue(value) if revenue else _fmt_rate(value)


def _fmt_slope(value: float, *, revenue: bool) -> str:
    if revenue:
        return f"{_fmt_revenue(value, decimals=2)}/day"
    return f"{value * 100:.3f}pp/day"


def _trend_phrase(trend: str) -> str:
    if trend == TREND_CONVERGING:
        return "rising"
    if trend == TREND_DECLINING:
        return "falling"
    return "flat"


def _severity_for_status(status: str) -> str:
    if status in (STATUS_ALREADY_ACHIEVED, STATUS_ON_TRACK):
        return SIGNAL_OK
    if status in (STATUS_STALLED, STATUS_EXPIRED):
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def _deadline_days(
    deadline: date | None,
    latest_ts: float | None,
) -> float | None:
    if deadline is None or latest_ts is None:
        return None
    latest_date = datetime.fromtimestamp(latest_ts, tz=UTC).date()
    return float((deadline - latest_date).days)


def _status(
    *,
    latest: float | None,
    target: float | None,
    slope: float,
    max_observed: float,
    deadline_days: float | None,
    projected: float | None,
    revenue: bool,
) -> str:
    if target is None or latest is None:
        return STATUS_INSUFFICIENT_DATA
    if latest >= target:
        return STATUS_ALREADY_ACHIEVED
    if deadline_days is None:
        return STATUS_NO_DEADLINE
    if deadline_days <= 0.0:
        return STATUS_EXPIRED
    if _is_flat_slope(slope, max_observed, revenue=revenue) or slope <= 0.0:
        return STATUS_STALLED
    if projected is not None and projected >= target:
        return STATUS_ON_TRACK
    return STATUS_BEHIND


def _metric_narrative(
    *,
    revenue: bool,
    sample_count: int,
    span_days: float,
    latest: float | None,
    target: float | None,
    trend: str,
    slope: float,
    max_observed: float,
    deadline: date | None,
    deadline_days: float | None,
    projected: float | None,
    days_to_target: float | None,
    required: float | None,
    status: str,
) -> str:
    label = _metric_label(revenue)
    target_text = _fmt_value(target, revenue=revenue) if target is not None else ""
    if sample_count < MIN_POINTS or latest is None or target is None:
        return _insufficient_narrative(revenue=revenue, target=target)
    if status == STATUS_ALREADY_ACHIEVED:
        return (
            f"Latest {label} ({_fmt_value(latest, revenue=revenue)}) already "
            f"meets the {target_text} goal."
        )
    if status == STATUS_NO_DEADLINE:
        if days_to_target is not None:
            unit = "day" if days_to_target == 1 else "days"
            return (
                f"Across {sample_count} checkpoint(s) spanning "
                f"{span_days:.0f} days, {label} is {_trend_phrase(trend)} at "
                f"{_fmt_value(latest, revenue=revenue)}. At the current pace "
                f"the {target_text} goal is ~{days_to_target:.0f} {unit} away. "
                "Add a deadline to get an on-track verdict."
            )
        if trend == TREND_CONVERGING:
            return (
                f"Across {sample_count} checkpoint(s) spanning "
                f"{span_days:.0f} days, {label} is {_trend_phrase(trend)} at "
                f"{_fmt_value(latest, revenue=revenue)}. The {target_text} "
                "goal is more than three years away at the current pace. "
                "Add a deadline to get an on-track verdict."
            )
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_days:.0f} "
            f"days, {label} is {_trend_phrase(trend)} at "
            f"{_fmt_value(latest, revenue=revenue)} and the current trend is "
            f"not moving toward the {target_text} goal. Add a deadline to "
            "get an on-track verdict."
        )
    if status == STATUS_EXPIRED:
        return (
            f"The {deadline.isoformat() if deadline else 'deadline'} has passed "
            f"and {label} ({_fmt_value(latest, revenue=revenue)}) has not "
            f"reached the {target_text} goal."
        )
    if status == STATUS_STALLED:
        return (
            f"{label.capitalize()} is {_trend_phrase(trend)} at "
            f"{_fmt_value(latest, revenue=revenue)} over {span_days:.0f} days "
            f"- stalled below the {target_text} goal. At the current trend the "
            f"deadline projection is "
            f"{_fmt_value(projected if projected is not None else latest, revenue=revenue)}."
        )
    if status == STATUS_ON_TRACK:
        headroom = ""
        if projected is not None and projected > target:
            headroom = (
                f" (~{_fmt_value(projected - target, revenue=revenue)} headroom)"
            )
        projected_text = _fmt_value(
            projected if projected is not None else latest,
            revenue=revenue,
        )
        return (
            f"Across {sample_count} checkpoint(s) spanning {span_days:.0f} "
            f"days, {label} is {_trend_phrase(trend)} at "
            f"{_fmt_value(latest, revenue=revenue)}. At the current pace it "
            f"reaches {projected_text} by "
            f"{deadline.isoformat() if deadline else 'the deadline'} - on "
            f"track for the {target_text} goal{headroom}."
        )
    required_text = ""
    if required is not None:
        required_text = (
            f" You need {_fmt_slope(required, revenue=revenue)} to hit the "
            f"goal on time (currently {_fmt_slope(slope, revenue=revenue)})."
        )
    projected_text = _fmt_value(
        projected if projected is not None else latest,
        revenue=revenue,
    )
    return (
        f"Across {sample_count} checkpoint(s) spanning {span_days:.0f} days, "
        f"{label} is {_trend_phrase(trend)} at "
        f"{_fmt_value(latest, revenue=revenue)}. At the current pace it "
        f"reaches only {projected_text} by "
        f"{deadline.isoformat() if deadline else 'the deadline'} - behind "
        f"the {target_text} goal.{required_text}"
    )


def _metric_signals(
    *,
    revenue: bool,
    latest: float | None,
    target: float | None,
    trend: str,
    status: str,
    confidence: str,
    projected: float | None,
    days_to_target: float | None,
    required: float | None,
    slope_gap: float | None,
    deadline: date | None,
) -> list[dict[str, Any]]:
    metric = _metric_label(revenue)
    signals: list[dict[str, Any]] = []

    if latest is not None and target is not None:
        signals.append(
            {
                "metric": metric,
                "label": "latest_actual",
                "value": latest,
                "severity": _severity_for_status(status),
                "display": (
                    f"Latest revenue: {_fmt_revenue(latest)}"
                    if revenue
                    else f"Latest conversion: {latest:.2%}"
                ),
            }
        )

    if trend != TREND_INSUFFICIENT_DATA:
        signals.append(
            {
                "metric": metric,
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

    if projected is not None and deadline is not None:
        signals.append(
            {
                "metric": metric,
                "label": "deadline_projection",
                "value": projected,
                "severity": _severity_for_status(status),
                "display": (
                    f"Projected by {deadline.isoformat()}: "
                    f"{_fmt_revenue(projected)}"
                    if revenue
                    else f"Projected by {deadline.isoformat()}: {projected:.2%}"
                ),
            }
        )

    if days_to_target is not None:
        signals.append(
            {
                "metric": metric,
                "label": "days_to_target",
                "value": days_to_target,
                "severity": SIGNAL_OK,
                "display": f"Days to goal at current pace: ~{days_to_target:.0f}",
            }
        )

    if required is not None:
        signals.append(
            {
                "metric": metric,
                "label": "required_slope",
                "value": required,
                "severity": (
                    SIGNAL_OK
                    if slope_gap is not None and slope_gap <= 0.0
                    else SIGNAL_CRITICAL
                ),
                "display": (
                    f"Required pace to hit deadline: {_fmt_slope(required, revenue=revenue)}"
                ),
            }
        )

    signals.append(
        {
            "metric": metric,
            "label": "confidence",
            "value": confidence,
            "severity": (
                SIGNAL_OK
                if confidence == CONFIDENCE_HIGH
                else SIGNAL_WATCH
            ),
            "display": f"Pacing confidence: {confidence.lower()}",
        }
    )
    return signals


def _evaluate_metric(
    rows: list[dict[str, Any]] | None,
    *,
    metric: str,
    target_value: float,
    deadline: date | None,
) -> dict[str, Any]:
    revenue = metric == METRIC_REVENUE
    points, latest_ts = _usable_series(rows, revenue=revenue)
    sample_count = len(points)
    latest = points[-1][1] if points else None
    target = _coerce_target(target_value, revenue=revenue)
    # Echo the goal actually used by the math. Unusable goals (non-finite,
    # non-positive, or boolean) surface as 0.0 so the payload never contains
    # NaN/Infinity, which would break JSON serialization downstream.
    echoed_target = target if target is not None else 0.0

    if sample_count < MIN_POINTS:
        return {
            "metric": metric,
            "target_value": echoed_target,
            "latest_actual": latest,
            "sample_count": sample_count,
            "span_days": None,
            "slope_per_day": None,
            "r_squared": None,
            "trend_label": TREND_INSUFFICIENT_DATA,
            "projected_value_at_deadline": None,
            "days_to_target": None,
            "deadline_days": _deadline_days(deadline, latest_ts),
            "gap_at_deadline": None,
            "required_slope_per_day": None,
            "slope_gap_per_day": None,
            "status": STATUS_INSUFFICIENT_DATA,
            "confidence": CONFIDENCE_INSUFFICIENT_DATA,
            "narrative": _insufficient_narrative(
                revenue=revenue,
                target=target,
            ),
            "signals": [],
        }

    span_days = round(points[-1][0] - points[0][0], 1)
    max_observed = max(p[1] for p in points)
    slope, r2 = _linear_fit(points)
    trend = _trend_label(slope, max_observed, revenue=revenue)
    confidence = _confidence(sample_count, span_days, r2)
    deadline_days = _deadline_days(deadline, latest_ts)
    ceiling = _ceiling(target, max_observed, revenue=revenue)
    days_to_target = _days_to_target(
        target,
        latest if latest is not None else 0.0,
        slope,
        max_observed,
        revenue=revenue,
    )

    projected: float | None = None
    gap: float | None = None
    required: float | None = None
    slope_gap: float | None = None
    if deadline_days is not None:
        if deadline_days <= 0.0:
            # The deadline is today or already passed; the retrospective
            # trend projection is meaningless, so compare the latest actual.
            projected = round(
                latest if latest is not None else 0.0,
                2 if revenue else 6,
            )
        else:
            projected = _projected(
                latest if latest is not None else 0.0,
                slope,
                deadline_days,
                ceiling,
                revenue=revenue,
            )
        if (
            deadline_days > 0.0
            and latest is not None
            and target is not None
            and latest < target
        ):
            required = (target - latest) / deadline_days
            slope_gap = round(required - slope, 6)
            required = round(required, 6)
        if target is not None and latest is not None:
            gap = round(target - projected, 2 if revenue else 6)

    status = _status(
        latest=latest,
        target=target,
        slope=slope,
        max_observed=max_observed,
        deadline_days=deadline_days,
        projected=projected,
        revenue=revenue,
    )
    narrative = _metric_narrative(
        revenue=revenue,
        sample_count=sample_count,
        span_days=span_days,
        latest=latest,
        target=target,
        trend=trend,
        slope=slope,
        max_observed=max_observed,
        deadline=deadline,
        deadline_days=deadline_days,
        projected=projected,
        days_to_target=days_to_target,
        required=required,
        status=status,
    )
    signals = _metric_signals(
        revenue=revenue,
        latest=latest,
        target=target,
        trend=trend,
        status=status,
        confidence=confidence,
        projected=projected,
        days_to_target=days_to_target,
        required=required,
        slope_gap=slope_gap,
        deadline=deadline,
    )
    return {
        "metric": metric,
        "target_value": echoed_target,
        "latest_actual": latest,
        "sample_count": sample_count,
        "span_days": span_days,
        "slope_per_day": slope,
        "r_squared": r2,
        "trend_label": trend,
        "projected_value_at_deadline": projected,
        "days_to_target": days_to_target,
        "deadline_days": deadline_days,
        "gap_at_deadline": gap,
        "required_slope_per_day": required,
        "slope_gap_per_day": slope_gap,
        "status": status,
        "confidence": confidence,
        "narrative": narrative,
        "signals": signals,
    }


_STATUS_SEVERITY: dict[str, int] = {
    STATUS_EXPIRED: 0,
    STATUS_STALLED: 1,
    STATUS_BEHIND: 2,
    STATUS_INSUFFICIENT_DATA: 3,
    STATUS_NO_DEADLINE: 4,
    STATUS_ON_TRACK: 5,
    STATUS_ALREADY_ACHIEVED: 6,
}


def _overall_status(metric_statuses: list[str]) -> str:
    if not metric_statuses:
        return STATUS_INSUFFICIENT_DATA
    return min(
        metric_statuses,
        key=lambda status: _STATUS_SEVERITY.get(status, 3),
    )


def _metric_summary(metric: dict[str, Any], deadline: date | None) -> str:
    revenue = metric["metric"] == METRIC_REVENUE
    label = _metric_label(revenue)
    status = metric["status"]
    target = metric["target_value"]
    target_text = _fmt_value(target, revenue=revenue)
    latest = metric["latest_actual"]
    if status == STATUS_INSUFFICIENT_DATA:
        return f"{label}: insufficient data to pace"
    if status == STATUS_ALREADY_ACHIEVED:
        return f"{label} already at the {target_text} goal"
    if status == STATUS_NO_DEADLINE:
        if metric["days_to_target"] is not None:
            return (
                f"{label}: no deadline set; {target_text} is "
                f"~{metric['days_to_target']:.0f} days away at the current pace"
            )
        if metric["trend_label"] == TREND_CONVERGING:
            return (
                f"{label}: no deadline set; {target_text} is more than "
                "three years away at the current pace"
            )
        return f"{label}: no deadline set and the trend is not moving toward {target_text}"
    if status == STATUS_EXPIRED:
        return (
            f"{label}: deadline passed with "
            f"{_fmt_value(latest if latest is not None else 0.0, revenue=revenue)} "
            f"vs {target_text}"
        )
    if status == STATUS_STALLED:
        return (
            f"{label}: stalled at "
            f"{_fmt_value(latest if latest is not None else 0.0, revenue=revenue)} "
            f"vs {target_text}"
        )
    projected = metric["projected_value_at_deadline"]
    projected_text = (
        _fmt_value(projected, revenue=revenue)
        if projected is not None
        else _fmt_value(latest if latest is not None else 0.0, revenue=revenue)
    )
    return (
        f"{label}: projected {projected_text} vs {target_text} by "
        f"{deadline.isoformat() if deadline else 'the deadline'} "
        f"({status.lower()})"
    )


def _overall_narrative(
    metrics: list[dict[str, Any]],
    deadline: date | None,
) -> str:
    summaries = [_metric_summary(metric, deadline) for metric in metrics]
    joined = "; ".join(summaries)
    text = f"Goal pacing across {len(metrics)} metric(s): {joined}."
    if any(
        metric["status"] in (STATUS_BEHIND, STATUS_STALLED, STATUS_EXPIRED)
        for metric in metrics
    ):
        text += (
            " Accelerate the metric(s) below the required pace before the "
            "deadline, or adjust the goal."
        )
    elif all(metric["status"] == STATUS_NO_DEADLINE for metric in metrics):
        text += " Add a deadline to get pacing verdicts."
    return text


def _project_deadline_days(
    rows: list[dict[str, Any]] | None,
    deadline: date | None,
) -> float | None:
    """Deadline offset from the newest usable checkpoint across all rows."""
    if deadline is None:
        return None
    latest_ts: float | None = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ts = _timestamp_seconds(row.get("recorded_at"))
        if ts is not None and (latest_ts is None or ts > latest_ts):
            latest_ts = ts
    return _deadline_days(deadline, latest_ts)


def build_outcome_tracker_goal_pacing(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
    target_conversion_rate: float | None = None,
    target_revenue: float | None = None,
    deadline: date | None = None,
) -> dict[str, Any]:
    """Compose goal-pacing verdicts for conversion and/or revenue goals.

    Args:
        rows: list of outcome_tracker row dicts. Each row must expose
            ``actual_conversion_rate`` / ``actual_revenue`` and
            ``recorded_at`` (datetime or ISO string); extra fields are
            ignored.
        project_id: owning project id (echoed back).
        target_conversion_rate: founder-set conversion goal in ``[0, 1]``.
        target_revenue: founder-set revenue goal (non-negative currency).
        deadline: date by which the goal(s) should be reached (``None``
            yields trend-based days-to-goal only).

    Returns:
        Dict matching :class:`OutcomeTrackerGoalPacingOut` (see the
        schema module).
    """
    metrics: list[dict[str, Any]] = []
    if target_conversion_rate is not None:
        metrics.append(
            _evaluate_metric(
                rows,
                metric=METRIC_CONVERSION,
                target_value=target_conversion_rate,
                deadline=deadline,
            )
        )
    if target_revenue is not None:
        metrics.append(
            _evaluate_metric(
                rows,
                metric=METRIC_REVENUE,
                target_value=target_revenue,
                deadline=deadline,
            )
        )

    if not metrics:
        return {
            "project_id": project_id,
            "deadline": deadline,
            "deadline_days": None,
            "metrics": [],
            "overall_status": STATUS_INSUFFICIENT_DATA,
            "narrative": (
                "Provide at least one of target_conversion_rate or "
                "target_revenue to evaluate goal pacing."
            ),
            "key_signals": [],
        }

    return {
        "project_id": project_id,
        "deadline": deadline,
        "deadline_days": _project_deadline_days(rows, deadline),
        "metrics": metrics,
        "overall_status": _overall_status(
            [metric["status"] for metric in metrics]
        ),
        "narrative": _overall_narrative(metrics, deadline),
        "key_signals": [
            signal
            for metric in metrics
            for signal in metric["signals"]
        ],
    }


__all__ = [
    "MIN_POINTS",
    "METRIC_CONVERSION",
    "METRIC_REVENUE",
    "TREND_CONVERGING",
    "TREND_FLAT",
    "TREND_DECLINING",
    "TREND_INSUFFICIENT_DATA",
    "STATUS_ALREADY_ACHIEVED",
    "STATUS_ON_TRACK",
    "STATUS_BEHIND",
    "STATUS_STALLED",
    "STATUS_EXPIRED",
    "STATUS_NO_DEADLINE",
    "STATUS_INSUFFICIENT_DATA",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_INSUFFICIENT_DATA",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_outcome_tracker_goal_pacing",
]
