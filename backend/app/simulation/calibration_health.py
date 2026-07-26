"""
Pure helpers for the calibration-health endpoint.

Siblings the outcomes-digest and architect-accuracy bridge:
emits a single payload with the dashboard's "is the system
calibrated?" health check, the top-miscalibrated architect,
and 7d / 30d / 90d rolling mean |variance| trend buckets so
the founder can answer "is the system getting more accurate
over time?".

Pure-Python (no SQL, no I/O) — the route layer joins
simulations + outcomes + domain_findings before invoking.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# Reuse the per-architect bridge's calibration
# bucketing for the top-miscalibrated-architect ranking.
from app.simulation.architect_accuracy_bridge import (
    LABEL_TIGHTEN,
    LABEL_LOOSEN,
    LABEL_TRUSTED,
    LABEL_INSUFFICIENT_DATA,
    bridge_architect_accuracy,
)

# Overall-health labels — mirrors the outcomes-digest
# confidence bucketing.
LABEL_WELL_CALIBRATED: str = "WELL_CALIBRATED"
LABEL_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
LABEL_POORLY_CALIBRATED: str = "POORLY_CALIBRATED"
LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VALID_HEALTH_LABELS: frozenset[str] = frozenset({
    LABEL_WELL_CALIBRATED,
    LABEL_NEEDS_ATTENTION,
    LABEL_POORLY_CALIBRATED,
    LABEL_INSUFFICIENT_DATA,
})

# Mean |variance| thresholds (in fraction terms).
WELL_CALIBRATED_MAX_MAE: float = 0.02
NEEDS_ATTENTION_MAX_MAE: float = 0.05
# anything ≥ 0.05 → POORLY_CALIBRATED

# Trend windows (days).
TREND_WINDOWS: tuple[tuple[str, int], ...] = (
    ("7d", 7),
    ("30d", 30),
    ("90d", 90),
)

# Cap on per-window rows so the trend doesn't blow up.
MAX_TREND_WINDOWS: int = 4

# Trajectory labels — derived from comparing the 7d mean
# |variance| against the 30d mean |variance|. The 7d window
# is the more recent snapshot; if it's lower than the 30d,
# the system is improving. Same 1pp threshold as the cluster
# / architect trends so the dashboard's wording stays
# consistent.
LABEL_IMPROVING: str = "IMPROVING"
LABEL_STABLE: str = "STABLE"
LABEL_DEGRADING: str = "DEGRADING"
LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VALID_TRAJECTORY_LABELS: frozenset[str] = frozenset({
    LABEL_IMPROVING,
    LABEL_STABLE,
    LABEL_DEGRADING,
    LABEL_INSUFFICIENT_DATA,
})

# Streak thresholds.
HEALTHY_STREAK_MAX_MAE: float = 0.02
# A day is "well-calibrated" when the rolling 7d mean
# |variance| ≤ HEALTHY_STREAK_MAX_MAE.
STREAK_DAY_WINDOW: int = 7
# How many of the most recent days to walk back when
# counting the streak. Capped so a stale system doesn't
# report a 365-day "streak" when the founder hasn't
# recorded sims in months.
MAX_STREAK_DAYS: int = 90


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _iso_to_dt(raw: object) -> datetime | None:
    """Coerce an ISO 8601 string / datetime to UTC. ``None`` on
    failure."""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, str):
        candidate = raw.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _overall_health(mean_abs_variance: float | None) -> str:
    """Bucket the mean |variance| into a health label.

    None → INSUFFICIENT_DATA. Same convention as the
    outcomes-digest confidence bucketing so the dashboard's
    wording stays consistent.
    """
    if mean_abs_variance is None:
        return LABEL_INSUFFICIENT_DATA
    if mean_abs_variance < WELL_CALIBRATED_MAX_MAE:
        return LABEL_WELL_CALIBRATED
    if mean_abs_variance < NEEDS_ATTENTION_MAX_MAE:
        return LABEL_NEEDS_ATTENTION
    return LABEL_POORLY_CALIBRATED


def _trajectory_label(
    mean_7d: float | None,
    mean_30d: float | None,
) -> str:
    """Compare 7d vs 30d mean |variance|.

    If 7d < 30d → IMPROVING (the recent window is tighter
    than the longer one — system is getting better).
    If 7d > 30d → DEGRADING. Within 1pp → STABLE. Either
    side missing → INSUFFICIENT_DATA.
    """
    if mean_7d is None or mean_30d is None:
        return LABEL_INSUFFICIENT_DATA
    delta = mean_7d - mean_30d
    if abs(delta) < 0.01:
        return LABEL_STABLE
    return LABEL_IMPROVING if delta < 0 else LABEL_DEGRADING


def _consecutive_well_calibrated_days(
    rows: list[tuple[datetime, float]],
    now: datetime,
) -> int:
    """Count back from ``now`` the consecutive days where the
    rolling ``STREAK_DAY_WINDOW``-day mean |variance| is
    well-calibrated (≤ HEALTHY_STREAK_MAX_MAE).

    Stops at the first day that doesn't qualify. Returns 0
    when the most recent day isn't well-calibrated or when
    there's no data.

    Capped at :data:`MAX_STREAK_DAYS` so a stale system
    doesn't report a multi-year "streak" when the founder
    hasn't recorded sims in months.
    """
    if not rows:
        return 0
    # Group by date (UTC).
    by_date: dict[str, list[float]] = {}
    for dt, var in rows:
        if dt is None:
            continue
        key = dt.strftime("%Y-%m-%d")
        by_date.setdefault(key, []).append(var)
    # Walk back from today.
    streak = 0
    for offset in range(MAX_STREAK_DAYS + 1):
        target = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        if target not in by_date:
            break
        # Rolling window: combine the target day with the
        # previous STREAK_DAY_WINDOW-1 days.
        window: list[float] = []
        for inner in range(offset, offset + STREAK_DAY_WINDOW):
            d_key = (now - timedelta(days=inner)).strftime("%Y-%m-%d")
            window.extend(by_date.get(d_key, []))
        if not window:
            break
        mean_window = sum(window) / len(window)
        if mean_window <= HEALTHY_STREAK_MAX_MAE:
            streak += 1
        else:
            break
    return streak


def _trend_buckets(
    rows: list[tuple[datetime, float]],
    now: datetime,
) -> list[dict]:
    """Compute per-window mean |variance|.

    Each row is ``(created_at_utc, abs_variance)``. Returns
    one dict per TREND_WINDOWS entry (7d / 30d / 90d),
    sorted by window length DESC. Window is ``[now - days,
    now]`` inclusive on both ends.
    """
    out: list[dict] = []
    for label, days in TREND_WINDOWS:
        start = now - timedelta(days=days)
        window_rows = [
            (dt, var)
            for dt, var in rows
            if dt is not None and start <= dt <= now
        ]
        if window_rows:
            mean_var = sum(
                v for _, v in window_rows
            ) / len(window_rows)
        else:
            mean_var = None
        out.append({
            "window": label,
            "days": days,
            "observation_count": len(window_rows),
            "mean_abs_variance": (
                round(mean_var, 6) if mean_var is not None else None
            ),
        })
    return out


def build_calibration_health(
    rows: list[tuple[object, object, object, list[dict] | None]],
    *,
    now: datetime | None = None,
) -> dict:
    """Build the calibration-health payload.

    Args:
        rows: list of ``(created_at, predicted, actual,
            findings)`` tuples. ``created_at`` may be a
            datetime or ISO 8601 string. ``predicted`` / ``actual``
            are coerced defensively (None / non-numeric / out-
            of-range rows are skipped). ``findings`` is the list
            of finding dicts from ``domain_findings``.
        now: the reference timestamp for the trend windows.
            Defaults to ``datetime.now(UTC)``. Tests can pin
            this for determinism.

    Returns:
        A dict matching :class:`CalibrationHealthOut`:

        * ``overall_health`` — WELL_CALIBRATED /
          NEEDS_ATTENTION / POORLY_CALIBRATED / UNKNOWN
          bucketed from mean |variance|.
        * ``mean_abs_variance`` — float.
        * ``observation_count`` — sims that contributed.
        * ``top_miscalibrated_architect`` — dict with name,
          |variance|, recommendation; None when no
          architect had bias data.
        * ``architect_accuracy_counts`` — histogram of
          recommendations across the batch (TIGHTEN /
          LOOSEN / TRUSTED / INVESTIGATE_BIAS / etc.).
        * ``trend_buckets`` — list of per-window rows
          (7d / 30d / 90d) with mean_abs_variance.
        * ``summary`` — one-line headline.
    """
    effective_now = now or datetime.now(tz=timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    else:
        effective_now = effective_now.astimezone(timezone.utc)

    abs_variances: list[float] = []
    trend_rows: list[tuple[datetime, float]] = []
    outcome_pairs: list[
        tuple[list[dict], tuple[float | None, float | None]]
    ] = []

    for created_at, predicted, actual, findings in rows:
        p = _safe_float(predicted)
        a = _safe_float(actual)
        if p is None or a is None:
            continue
        abs_var = abs(p - a)
        abs_variances.append(abs_var)
        dt = _iso_to_dt(created_at)
        if dt is not None:
            trend_rows.append((dt, abs_var))
        outcome_pairs.append(
            (
                findings if isinstance(findings, list) else [],
                (p, a),
            )
        )

    observation_count = len(abs_variances)
    if observation_count == 0:
        return {
            "overall_health": LABEL_INSUFFICIENT_DATA,
            "mean_abs_variance": None,
            "observation_count": 0,
            "top_miscalibrated_architect": None,
            "architect_accuracy_counts": {
                LABEL_TIGHTEN: 0,
                LABEL_LOOSEN: 0,
                LABEL_TRUSTED: 0,
            },
            "trend_buckets": _trend_buckets([], effective_now),
            "health_trajectory": LABEL_INSUFFICIENT_DATA,
            "consecutive_well_calibrated_days": 0,
            "summary": "No data — calibration health unknown.",
        }

    mean_abs_variance = sum(abs_variances) / observation_count
    overall = _overall_health(mean_abs_variance)

    # Reuse the bridge so the dashboard sees consistent
    # recommendation labels between /architect-accuracy and
    # /calibration-health.
    bridge = bridge_architect_accuracy(outcome_pairs)
    by_architect = bridge.get("by_architect") or []
    # Aggregate recommendation counts.
    accuracy_counts = {
        LABEL_TIGHTEN: 0,
        LABEL_LOOSEN: 0,
        LABEL_TRUSTED: 0,
    }
    for row in by_architect:
        rec = row.get("recommendation")
        if rec in accuracy_counts:
            accuracy_counts[rec] += 1

    # Top miscalibrated architect — highest |calibration_variance|
    # among the bridge rows. None when no architect had bias
    # data (e.g. all INSUFFICIENT_DATA).
    top_payload: dict | None = None
    candidate_rows = [
        r for r in by_architect
        if r.get("calibration_variance") is not None
    ]
    if candidate_rows:
        top = max(
            candidate_rows,
            key=lambda r: abs(r["calibration_variance"]),
        )
        top_payload = {
            "architect_name": top["architect_name"],
            "abs_calibration_variance": round(
                abs(top["calibration_variance"]), 6
            ),
            "calibration_variance": top["calibration_variance"],
            "calibration_direction": top.get(
                "calibration_direction", "INSUFFICIENT_DATA"
            ),
            "recommendation": top.get(
                "recommendation", LABEL_TRUSTED
            ),
            "finding_count": top.get("finding_count", 0),
        }

    summary = (
        f"Calibration health: {overall} "
        f"(mean |variance|={round(mean_abs_variance, 4)}, "
        f"{observation_count} sim(s))"
    )

    # Trend + trajectory.
    trend_buckets = _trend_buckets(trend_rows, effective_now)
    by_window = {b["window"]: b["mean_abs_variance"] for b in trend_buckets}
    trajectory = _trajectory_label(
        by_window.get("7d"), by_window.get("30d"),
    )
    streak = _consecutive_well_calibrated_days(
        trend_rows, effective_now,
    )

    return {
        "overall_health": overall,
        "mean_abs_variance": round(mean_abs_variance, 6),
        "observation_count": observation_count,
        "top_miscalibrated_architect": top_payload,
        "architect_accuracy_counts": accuracy_counts,
        "trend_buckets": trend_buckets,
        "health_trajectory": trajectory,
        "consecutive_well_calibrated_days": streak,
        "summary": summary,
    }


__all__ = [
    "LABEL_WELL_CALIBRATED",
    "LABEL_NEEDS_ATTENTION",
    "LABEL_POORLY_CALIBRATED",
    "LABEL_INSUFFICIENT_DATA",
    "VALID_HEALTH_LABELS",
    "WELL_CALIBRATED_MAX_MAE",
    "NEEDS_ATTENTION_MAX_MAE",
    "LABEL_IMPROVING",
    "LABEL_STABLE",
    "LABEL_DEGRADING",
    "VALID_TRAJECTORY_LABELS",
    "HEALTHY_STREAK_MAX_MAE",
    "STREAK_DAY_WINDOW",
    "MAX_STREAK_DAYS",
    "TREND_WINDOWS",
    "build_calibration_health",
]