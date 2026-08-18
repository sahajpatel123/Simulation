"""Validation-momentum forecast for a project's evidence history.

The evidence digest answers *how much* risk has been validated; the
validation timeline answers *when it happened*. This module answers *how
fast validation is happening and when the remaining work will finish*:

* evidence cadence — experiments per week since the first logged result,
  plus the recent 28-day cadence and an accelerating/steady/decelerating
  trend;
* coverage velocity — how many assumptions receive their first evidence per
  week, projected forward to full coverage;
* de-risking velocity — how many assumptions reach ``DE_RISKED`` for the
  first time per week, projected forward to an optional de-risked target
  (default 100%).

Status and policy are inherited from :func:`build_validation_timeline`, so
the momentum numbers always agree with the timeline's final snapshot:
decisive PASS/FAIL wins, trailing INCONCLUSIVE does not erase an earlier
decisive outcome, and hidden/orphaned rows are excluded.

Pure module (no DB, no I/O): the route passes already-loaded assumption and
evidence rows plus an optional ``now`` (used only to bound the recent
window and stamp projected dates), so every value is deterministic and
easily testable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

from app.simulation.assumption_evidence_digest import (
    STATUS_CHALLENGED,
    STATUS_DE_RISKED,
    STATUS_INCONCLUSIVE,
    STATUS_PENDING,
)
from app.simulation.validation_timeline import build_validation_timeline

MOMENTUM_MODEL: str = "validation_momentum_v1"

# Recent-window length used for cadence comparison (calendar days).
RECENT_WINDOW_DAYS: int = 28

# Recent cadence must exceed/fall below the overall cadence by these
# multiples before we call the trend accelerating or decelerating.
TREND_ACCELERATING_RATIO: float = 1.2
TREND_DECELERATING_RATIO: float = 0.8

# Forecast confidence thresholds: at least this many events spread over at
# least this many days before projected dates are treated as directional.
MIN_CONFIDENT_EVENTS: int = 3
MIN_CONFIDENT_SPAN_DAYS: float = 14.0

# Sanity cap for projected horizons (10 years) so a near-zero velocity can
# never produce a payload with absurd dates.
MAX_FORECAST_WEEKS: float = 520.0

TREND_NO_EVIDENCE: str = "NO_EVIDENCE"
TREND_INSUFFICIENT: str = "INSUFFICIENT"
TREND_ACCELERATING: str = "ACCELERATING"
TREND_STEADY: str = "STEADY"
TREND_DECELERATING: str = "DECELERATING"


def _coerce_timestamp(value: Any) -> datetime | None:
    """Coerce a created-at value to an aware UTC datetime (or ``None``)."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=UTC)
        )
    return None


def _span_weeks(span_days: float | None) -> float | None:
    # A sub-day span cannot support a meaningful per-week rate: two
    # experiments logged an hour apart imply nothing about weekly cadence.
    if span_days is None or span_days < 1.0:
        return None
    return span_days / 7.0


def _velocity(
    distinct_timestamps: list[datetime],
    span_weeks: float | None,
) -> float | None:
    """Distinct first-occurrence timestamps per week, or ``None``."""
    if span_weeks is None or not distinct_timestamps:
        return None
    return len(distinct_timestamps) / span_weeks


def _project_weeks(
    remaining: int,
    velocity: float | None,
) -> tuple[float | None, list[str]]:
    """Project weeks to clear ``remaining`` at ``velocity``/week.

    Returns ``(weeks, caveats)``. A projected calendar date is computed by the
    caller from ``weeks``; if the horizon is unknown it is ``None``.
    """
    caveats: list[str] = []
    if remaining <= 0:
        return 0.0, caveats
    if velocity is None or velocity <= 0:
        return None, caveats
    weeks = min(remaining / velocity, MAX_FORECAST_WEEKS)
    if weeks >= MAX_FORECAST_WEEKS:
        caveats.append(
            "Projected horizon exceeds 10 years — treat the date as a "
            "'too slow to plan around' signal rather than a schedule."
        )
    return round(weeks, 2), caveats


def _timestamp_by_event_id(events: list[dict[str, Any]]) -> dict[int, datetime]:
    out: dict[int, datetime] = {}
    for event in events:
        event_id = event.get("event_id")
        timestamp = _coerce_timestamp(event.get("created_at"))
        if isinstance(event_id, int) and timestamp is not None:
            out[event_id] = timestamp
    return out


def _cadence_insights(
    trend: str,
    overall: float | None,
    recent: float | None,
    events: int,
) -> list[str]:
    if trend == TREND_NO_EVIDENCE:
        return [
            "No validation experiments logged yet — run the validation-"
            "experiment plan and log the first result to start tracking "
            "momentum."
        ]
    if trend == TREND_INSUFFICIENT:
        return [
            "Log a few more experiments over separate days before the "
            "cadence trend becomes meaningful."
        ]
    if trend == TREND_ACCELERATING and recent is not None:
        return [
            f"Validation cadence is accelerating — {recent:.1f} "
            f"experiments/week in the last {RECENT_WINDOW_DAYS} days vs "
            f"{overall:.1f} overall since the first experiment."
        ]
    if trend == TREND_DECELERATING and recent is not None:
        return [
            f"Validation cadence is slowing — {recent:.1f} "
            f"experiments/week in the last {RECENT_WINDOW_DAYS} days vs "
            f"{overall:.1f} overall. Protect a regular experiment rhythm."
        ]
    if recent is not None and overall is not None:
        return [
            f"Validation cadence is steady at {recent:.1f} "
            f"experiments/week ({events} logged experiments)."
        ]
    return []


def build_validation_momentum(
    *,
    assumptions: list[Any] | None,
    evidence: list[Any] | None,
    project_id: int,
    target_de_risked_pct: float = 1.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the validation-momentum forecast for a project.

    Args:
        assumptions: every visible ``Assumption`` row for the project (any
            order; hidden rows are excluded).
        evidence: every ``AssumptionEvidence`` row for the project (any
            order; orphaned rows are excluded).
        project_id: owning project, echoed back for client routing.
        target_de_risked_pct: share of assumptions to de-risk before the
            horizon is reached (0.5–1.0).
        now: reference clock for the recent window and projected dates;
            defaults to the current UTC time.

    Returns:
        Dict matching :class:`ValidationMomentumOut`.
    """
    reference_now = now or datetime.now(UTC)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=UTC)

    timeline = build_validation_timeline(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project_id,
    )
    events = timeline["events"]
    assumption_rows = timeline["assumptions"]

    total_assumptions = int(timeline["total_assumptions"])
    total_evidence_rows = int(timeline["total_evidence_rows"])
    de_risked_count = sum(
        row["status"] == STATUS_DE_RISKED for row in assumption_rows
    )
    challenged_count = sum(
        row["status"] == STATUS_CHALLENGED for row in assumption_rows
    )
    inconclusive_count = sum(
        row["status"] == STATUS_INCONCLUSIVE for row in assumption_rows
    )
    pending_count = sum(
        row["status"] == STATUS_PENDING for row in assumption_rows
    )
    assumptions_with_evidence = sum(
        int(row["evidence_count"]) > 0 for row in assumption_rows
    )
    validation_score = (
        round(de_risked_count / total_assumptions, 4)
        if total_assumptions > 0
        else None
    )
    evidence_coverage_pct = (
        round(assumptions_with_evidence / total_assumptions, 4)
        if total_assumptions > 0
        else None
    )

    timestamps = sorted(
        timestamp
        for timestamp in (
            _coerce_timestamp(event.get("created_at")) for event in events
        )
        if timestamp is not None
    )
    first_evidence_at = timestamps[0] if timestamps else None
    latest_evidence_at = timestamps[-1] if timestamps else None
    evidence_span_days = (
        (latest_evidence_at - first_evidence_at).total_seconds() / 86400.0
        if first_evidence_at is not None and latest_evidence_at is not None
        else None
    )
    span_weeks = _span_weeks(evidence_span_days)

    # Event cadence (raw experiments per week).
    overall_events_per_week = (
        round(total_evidence_rows / span_weeks, 3)
        if span_weeks is not None
        else None
    )
    recent_cutoff = reference_now - timedelta(days=RECENT_WINDOW_DAYS)
    events_last_28_days = sum(
        1
        for timestamp in timestamps
        if recent_cutoff < timestamp <= reference_now
    )
    recent_events_per_week = (
        round(events_last_28_days / (RECENT_WINDOW_DAYS / 7.0), 3)
        if events_last_28_days > 0
        else 0.0
    )

    if not events:
        trend = TREND_NO_EVIDENCE
    elif len(events) < 2 or evidence_span_days is None or evidence_span_days <= 0:
        trend = TREND_INSUFFICIENT
    elif (
        recent_events_per_week is not None
        and overall_events_per_week is not None
        and overall_events_per_week > 0
    ):
        ratio = recent_events_per_week / overall_events_per_week
        if ratio >= TREND_ACCELERATING_RATIO:
            trend = TREND_ACCELERATING
        elif ratio <= TREND_DECELERATING_RATIO:
            trend = TREND_DECELERATING
        else:
            trend = TREND_STEADY
    else:
        trend = TREND_INSUFFICIENT

    # Distinct first-occurrence velocities (assumptions per week).
    timestamp_by_event_id = _timestamp_by_event_id(events)
    first_evidence_stamps = sorted(
        timestamp_by_event_id[row["first_evidence_event_id"]]
        for row in assumption_rows
        if row.get("first_evidence_event_id") is not None
        and row["first_evidence_event_id"] in timestamp_by_event_id
    )
    first_de_risked_stamps = sorted(
        timestamp_by_event_id[row["first_de_risked_event_id"]]
        for row in assumption_rows
        if row.get("first_de_risked_event_id") is not None
        and row["first_de_risked_event_id"] in timestamp_by_event_id
    )
    coverage_velocity = _velocity(first_evidence_stamps, span_weeks)
    de_risk_velocity = _velocity(first_de_risked_stamps, span_weeks)

    # Forecasts.
    remaining_for_coverage = max(0, total_assumptions - assumptions_with_evidence)
    target_count = max(
        de_risked_count,
        int(ceil(total_assumptions * target_de_risked_pct)),
    )
    remaining_for_target = max(0, target_count - de_risked_count)

    weeks_to_full_coverage, coverage_caveats = _project_weeks(
        remaining_for_coverage, coverage_velocity
    )
    weeks_to_de_risked_target, de_risk_caveats = _project_weeks(
        remaining_for_target, de_risk_velocity
    )

    caveats: list[str] = []
    if not events:
        caveats.append(
            "No evidence logged — cadence and projected dates are "
            "unavailable until the first experiment is recorded."
        )
    elif (
        total_evidence_rows < MIN_CONFIDENT_EVENTS
        or evidence_span_days is None
        or evidence_span_days < MIN_CONFIDENT_SPAN_DAYS
    ):
        caveats.append(
            "Evidence history is under two weeks (or too sparse) — "
            "projected dates are directional, not firm."
        )
    if (
        remaining_for_coverage > 0
        and (coverage_velocity is None or coverage_velocity <= 0)
        and events
    ):
        caveats.append(
            "No assumption has received its first evidence yet — log any "
            "experiment to start projecting full coverage."
        )
    if (
        remaining_for_target > 0
        and (de_risk_velocity is None or de_risk_velocity <= 0)
        and events
    ):
        caveats.append(
            "No assumption has been de-risked yet — decisive PASS "
            "experiments are needed before a de-risking date can be "
            "projected."
        )
    caveats.extend(coverage_caveats)
    caveats.extend(de_risk_caveats)

    confident = (
        remaining_for_coverage == 0 and remaining_for_target == 0
    ) or (
        total_evidence_rows >= MIN_CONFIDENT_EVENTS
        and evidence_span_days is not None
        and evidence_span_days >= MIN_CONFIDENT_SPAN_DAYS
        and (
            weeks_to_full_coverage is not None
            or weeks_to_de_risked_target is not None
        )
    )

    projected_full_coverage_at = (
        reference_now + timedelta(weeks=weeks_to_full_coverage)
        if weeks_to_full_coverage is not None
        else None
    )
    projected_de_risked_at = (
        reference_now + timedelta(weeks=weeks_to_de_risked_target)
        if weeks_to_de_risked_target is not None
        else None
    )

    insights = _cadence_insights(
        trend=trend,
        overall=overall_events_per_week,
        recent=recent_events_per_week,
        events=total_evidence_rows,
    )
    if (
        remaining_for_coverage > 0
        and weeks_to_full_coverage is not None
        and projected_full_coverage_at is not None
    ):
        insights.append(
            f"Every assumption will have evidence in ~{weeks_to_full_coverage:.0f} "
            f"weeks ({projected_full_coverage_at:%Y-%m-%d}) at the current "
            "first-evidence pace."
        )
    if (
        remaining_for_target > 0
        and weeks_to_de_risked_target is not None
        and projected_de_risked_at is not None
    ):
        insights.append(
            f"Projected to reach {target_de_risked_pct:.0%} de-risked in "
            f"~{weeks_to_de_risked_target:.0f} weeks "
            f"({projected_de_risked_at:%Y-%m-%d})."
        )
    if total_assumptions > 0 and de_risked_count >= total_assumptions:
        insights.append(
            "All visible assumptions are de-risked — keep logging evidence "
            "as the product evolves."
        )
    if challenged_count > 0:
        insights.append(
            f"{challenged_count} challenged assumption(s) are active risk — "
            "rework or replace them so they stop distorting the forecast."
        )

    return {
        "project_id": int(timeline["project_id"]),
        "counts": {
            "total_assumptions": total_assumptions,
            "total_evidence_rows": total_evidence_rows,
            "assumptions_with_evidence": assumptions_with_evidence,
            "de_risked_count": de_risked_count,
            "challenged_count": challenged_count,
            "inconclusive_count": inconclusive_count,
            "pending_count": pending_count,
            "evidence_coverage_pct": (
                round(evidence_coverage_pct, 4)
                if evidence_coverage_pct is not None
                else None
            ),
            "validation_score": (
                round(validation_score, 4)
                if validation_score is not None
                else None
            ),
        },
        "velocity": {
            "trend": trend,
            "overall_events_per_week": overall_events_per_week,
            "recent_events_per_week": (
                round(recent_events_per_week, 3)
                if recent_events_per_week is not None
                else None
            ),
            "recent_window_days": RECENT_WINDOW_DAYS,
            "events_last_28_days": events_last_28_days,
            "first_evidence_at": first_evidence_at,
            "latest_evidence_at": latest_evidence_at,
            "evidence_span_days": (
                round(evidence_span_days, 3)
                if evidence_span_days is not None
                else None
            ),
            "coverage_velocity_per_week": (
                round(coverage_velocity, 3)
                if coverage_velocity is not None
                else None
            ),
            "de_risk_velocity_per_week": (
                round(de_risk_velocity, 3)
                if de_risk_velocity is not None
                else None
            ),
        },
        "forecast": {
            "target_de_risked_pct": round(target_de_risked_pct, 4),
            "target_de_risked_count": target_count,
            "remaining_for_coverage": remaining_for_coverage,
            "remaining_for_target": remaining_for_target,
            "weeks_to_full_coverage": weeks_to_full_coverage,
            "projected_full_coverage_at": projected_full_coverage_at,
            "weeks_to_de_risked_target": weeks_to_de_risked_target,
            "projected_de_risked_at": projected_de_risked_at,
            "confident": confident,
            "caveats": caveats,
        },
        "insights": insights,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": MOMENTUM_MODEL,
            "recent_window_days": RECENT_WINDOW_DAYS,
            "status_labels": {
                STATUS_DE_RISKED: "latest decisive experiment PASSED",
                STATUS_CHALLENGED: "latest decisive experiment FAILED",
                STATUS_INCONCLUSIVE: (
                    "has evidence but no decisive PASS/FAIL"
                ),
                STATUS_PENDING: "no logged evidence",
            },
            "velocity_policy": (
                "coverage velocity counts first evidence per assumption; "
                "de-risk velocity counts first DE_RISKED state per "
                "assumption; recent cadence uses the trailing 28 days"
            ),
            "forecast_policy": (
                "horizons project current velocity linearly and are capped "
                "at 520 weeks"
            ),
        },
    }


__all__ = ["build_validation_momentum"]
