"""Portfolio-level rollup for project validation-momentum forecasts.

The project momentum builder remains the source of truth for status policy,
cadence, and forecast math.  This module only composes those project payloads
into a founder-facing portfolio view: projects are ranked by validation need,
counts and velocities are summed for work that can proceed in parallel, and a
portfolio trend is marked mixed when projects disagree.

The helper is pure Python.  The API route supplies already-loaded project,
assumption, and evidence rows, which keeps the aggregation deterministic and
straightforward to test without a database.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from math import ceil
from typing import Any, Mapping

from app.simulation.validation_momentum import (
    MAX_FORECAST_WEEKS,
    TREND_ACCELERATING,
    TREND_DECELERATING,
    TREND_INSUFFICIENT,
    TREND_NO_EVIDENCE,
    TREND_STEADY,
    build_validation_momentum,
)

PORTFOLIO_MOMENTUM_MODEL: str = "portfolio_validation_momentum_v1"
PROJECT_STATUS_NO_ASSUMPTIONS: str = "NO_ASSUMPTIONS"
PROJECT_STATUS_NO_EVIDENCE: str = "NO_EVIDENCE"
PROJECT_STATUS_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
PROJECT_STATUS_ON_TRACK: str = "ON_TRACK"
PROJECT_STATUS_COMPLETE: str = "COMPLETE"
PORTFOLIO_TREND_MIXED: str = "MIXED"


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed > 0 else 0


def _title(value: Any, project_id: int) -> str:
    text = str(value).strip() if value is not None else ""
    return text or f"Project {project_id}"


def _project_status(counts: Mapping[str, Any], forecast: Mapping[str, Any]) -> str:
    total_assumptions = _positive_int(counts.get("total_assumptions"))
    if total_assumptions == 0:
        return PROJECT_STATUS_NO_ASSUMPTIONS
    if _positive_int(counts.get("total_evidence_rows")) == 0:
        return PROJECT_STATUS_NO_EVIDENCE
    if (
        _positive_int(forecast.get("remaining_for_target")) > 0
        or counts.get("challenged_count", 0) > 0
        or forecast.get("confident") is False
    ):
        return PROJECT_STATUS_NEEDS_ATTENTION
    if _positive_int(forecast.get("remaining_for_coverage")) > 0:
        return PROJECT_STATUS_ON_TRACK
    return PROJECT_STATUS_COMPLETE


def _focus_reason(
    *,
    status: str,
    counts: Mapping[str, Any],
    velocity: Mapping[str, Any],
    forecast: Mapping[str, Any],
) -> str:
    if status == PROJECT_STATUS_NO_ASSUMPTIONS:
        return "Add at least one assumption before validation momentum can be measured."
    if status == PROJECT_STATUS_NO_EVIDENCE:
        return "No evidence is logged — run the first validation experiment here."
    challenged_count = _positive_int(counts.get("challenged_count"))
    remaining_target = _positive_int(forecast.get("remaining_for_target"))
    trend = str(velocity.get("trend") or TREND_INSUFFICIENT)
    if challenged_count > 0:
        return (
            f"{challenged_count} challenged assumption(s) need a recovery plan "
            "before this project is de-risked."
        )
    if trend == TREND_DECELERATING:
        return "Cadence is slowing — restore a regular experiment rhythm."
    if remaining_target > 0:
        return f"{remaining_target} assumption(s) remain before the de-risked target."
    if status == PROJECT_STATUS_COMPLETE:
        return "Target reached — keep logging evidence as the product changes."
    return "Keep the current experiment cadence and close the remaining coverage gap."


def _portfolio_trend(project_payloads: list[dict[str, Any]]) -> str:
    trends = [
        str(row["trend"])
        for row in project_payloads
        if row["trend"] in {
            TREND_ACCELERATING,
            TREND_DECELERATING,
            TREND_STEADY,
        }
    ]
    if not trends:
        if any(row["total_evidence_rows"] > 0 for row in project_payloads):
            return TREND_INSUFFICIENT
        return TREND_NO_EVIDENCE
    counts = Counter(trends)
    if len(counts) == 1:
        return trends[0]
    return PORTFOLIO_TREND_MIXED


def _parallel_horizon(remaining: int, velocity: float | None) -> float | None:
    if remaining <= 0:
        return 0.0
    if velocity is None or velocity <= 0:
        return None
    return round(min(remaining / velocity, MAX_FORECAST_WEEKS), 2)


def _sum_optional(values: list[Any]) -> float | None:
    usable = [float(value) for value in values if value is not None and value > 0]
    return round(sum(usable), 3) if usable else None


def build_portfolio_validation_momentum(
    *,
    user_id: int,
    project_rows: list[Any] | None,
    target_de_risked_pct: float = 1.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a portfolio digest from project rows and their evidence.

    Each item in ``project_rows`` must expose ``project_id``, optionally
    ``project_title``, and ``assumptions`` / ``evidence`` lists.  Forecast
    horizons assume projects can be worked in parallel; the payload calls
    that policy out explicitly so a founder does not mistake the rollup for a
    sequential calendar commitment.
    """
    reference_now = now or datetime.now(UTC)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=UTC)
    target = min(max(float(target_de_risked_pct), 0.5), 1.0)

    project_payloads: list[dict[str, Any]] = []
    for raw_project in project_rows or []:
        project_id = _positive_int(_value(raw_project, "project_id"))
        if project_id == 0:
            continue
        momentum = build_validation_momentum(
            assumptions=_value(raw_project, "assumptions", []) or [],
            evidence=_value(raw_project, "evidence", []) or [],
            project_id=project_id,
            target_de_risked_pct=target,
            now=reference_now,
        )
        counts = momentum["counts"]
        velocity = momentum["velocity"]
        forecast = momentum["forecast"]
        status = _project_status(counts, forecast)
        project_payloads.append({
            "project_id": project_id,
            "project_title": _title(
                _value(raw_project, "project_title"), project_id
            ),
            "status": status,
            "trend": velocity["trend"],
            "total_assumptions": counts["total_assumptions"],
            "total_evidence_rows": counts["total_evidence_rows"],
            "assumptions_with_evidence": counts["assumptions_with_evidence"],
            "de_risked_count": counts["de_risked_count"],
            "challenged_count": counts["challenged_count"],
            "pending_count": counts["pending_count"],
            "evidence_coverage_pct": counts["evidence_coverage_pct"],
            "validation_score": counts["validation_score"],
            "coverage_velocity_per_week": velocity["coverage_velocity_per_week"],
            "de_risk_velocity_per_week": velocity["de_risk_velocity_per_week"],
            "remaining_for_coverage": forecast["remaining_for_coverage"],
            "remaining_for_target": forecast["remaining_for_target"],
            "weeks_to_full_coverage": forecast["weeks_to_full_coverage"],
            "weeks_to_de_risked_target": forecast["weeks_to_de_risked_target"],
            "latest_evidence_at": velocity["latest_evidence_at"],
            "confident": forecast["confident"],
            "focus_reason": _focus_reason(
                status=status,
                counts=counts,
                velocity=velocity,
                forecast=forecast,
            ),
        })

    status_order = {
        PROJECT_STATUS_NO_EVIDENCE: 0,
        PROJECT_STATUS_NEEDS_ATTENTION: 1,
        PROJECT_STATUS_ON_TRACK: 2,
        PROJECT_STATUS_COMPLETE: 3,
        PROJECT_STATUS_NO_ASSUMPTIONS: 4,
    }
    project_payloads.sort(
        key=lambda row: (
            status_order.get(row["status"], 5),
            -row["remaining_for_target"],
            -row["challenged_count"],
            row["project_id"],
        )
    )
    for rank, row in enumerate(project_payloads, start=1):
        row["rank"] = rank

    total_assumptions = sum(row["total_assumptions"] for row in project_payloads)
    total_evidence_rows = sum(row["total_evidence_rows"] for row in project_payloads)
    assumptions_with_evidence = sum(
        row["assumptions_with_evidence"] for row in project_payloads
    )
    de_risked_count = sum(row["de_risked_count"] for row in project_payloads)
    challenged_count = sum(row["challenged_count"] for row in project_payloads)
    pending_count = sum(row["pending_count"] for row in project_payloads)
    target_count = max(
        de_risked_count,
        int(ceil(total_assumptions * target)),
    )
    remaining_for_coverage = max(total_assumptions - assumptions_with_evidence, 0)
    remaining_for_target = max(target_count - de_risked_count, 0)
    coverage_velocity = _sum_optional(
        [row["coverage_velocity_per_week"] for row in project_payloads]
    )
    de_risk_velocity = _sum_optional(
        [row["de_risk_velocity_per_week"] for row in project_payloads]
    )
    weeks_to_full_coverage = _parallel_horizon(
        remaining_for_coverage, coverage_velocity
    )
    weeks_to_de_risked_target = _parallel_horizon(
        remaining_for_target, de_risk_velocity
    )

    projects_with_evidence = sum(
        row["total_evidence_rows"] > 0 for row in project_payloads
    )
    projects_without_evidence = len(project_payloads) - projects_with_evidence
    projects_needing_attention = sum(
        row["status"] in {
            PROJECT_STATUS_NO_EVIDENCE,
            PROJECT_STATUS_NEEDS_ATTENTION,
        }
        for row in project_payloads
    )
    projects_complete = sum(
        row["status"] == PROJECT_STATUS_COMPLETE for row in project_payloads
    )
    evidence_coverage_pct = (
        round(assumptions_with_evidence / total_assumptions, 4)
        if total_assumptions > 0
        else None
    )
    validation_score = (
        round(de_risked_count / total_assumptions, 4)
        if total_assumptions > 0
        else None
    )
    focus = project_payloads[0] if projects_needing_attention else None
    portfolio_trend = _portfolio_trend(project_payloads)

    insights: list[str] = []
    if not project_payloads:
        insights.append("No projects found — create a project to start a validation plan.")
    elif focus is not None:
        insights.append(
            f"Focus first on {focus['project_title']}: {focus['focus_reason']}"
        )
    if projects_without_evidence > 0:
        insights.append(
            f"{projects_without_evidence} project(s) have no logged evidence yet."
        )
    if portfolio_trend == PORTFOLIO_TREND_MIXED:
        insights.append(
            "Validation pace is mixed across projects — use the ranked list "
            "to protect the slowest high-risk work."
        )
    elif portfolio_trend == TREND_ACCELERATING:
        insights.append("Validation pace is accelerating across the active portfolio.")
    elif portfolio_trend == TREND_DECELERATING:
        insights.append("Validation pace is decelerating across the active portfolio.")
    if remaining_for_target == 0 and total_assumptions > 0:
        insights.append(
            f"The portfolio has reached the {target:.0%} de-risked target."
        )

    caveats: list[str] = []
    if projects_without_evidence > 0:
        caveats.append(
            "Portfolio velocity excludes projects without enough dated evidence "
            "to estimate a weekly pace."
        )
    if remaining_for_coverage > 0 or remaining_for_target > 0:
        caveats.append(
            "Portfolio dates assume projects can be validated in parallel at their "
            "observed pace; they are planning signals, not commitments."
        )
    if total_assumptions == 0 and project_payloads:
        caveats.append("No visible assumptions exist across the portfolio yet.")

    return {
        "user_id": _positive_int(user_id),
        "generated_at": reference_now,
        "summary": {
            "project_count": len(project_payloads),
            "projects_with_evidence": projects_with_evidence,
            "projects_without_evidence": projects_without_evidence,
            "projects_needing_attention": projects_needing_attention,
            "projects_complete": projects_complete,
            "total_assumptions": total_assumptions,
            "total_evidence_rows": total_evidence_rows,
            "assumptions_with_evidence": assumptions_with_evidence,
            "de_risked_count": de_risked_count,
            "challenged_count": challenged_count,
            "pending_count": pending_count,
            "evidence_coverage_pct": evidence_coverage_pct,
            "validation_score": validation_score,
            "coverage_velocity_per_week": coverage_velocity,
            "de_risk_velocity_per_week": de_risk_velocity,
            "target_de_risked_pct": round(target, 4),
            "remaining_for_coverage": remaining_for_coverage,
            "remaining_for_target": remaining_for_target,
            "weeks_to_full_coverage": weeks_to_full_coverage,
            "weeks_to_de_risked_target": weeks_to_de_risked_target,
            "portfolio_trend": portfolio_trend,
            "focus_project_id": focus["project_id"] if focus else None,
            "focus_project_title": focus["project_title"] if focus else None,
            "focus_reason": focus["focus_reason"] if focus else (
                "No project needs attention right now."
                if project_payloads
                else "Create a project to begin validation."
            ),
            "insights": insights,
            "caveats": caveats,
        },
        "projects": project_payloads,
        "meta": {
            "model": PORTFOLIO_MOMENTUM_MODEL,
            "generated_at": reference_now.isoformat(),
            "target_de_risked_pct": round(target, 4),
            "project_sort_policy": (
                "no evidence first, then attention status, remaining target, "
                "challenged count, and project id"
            ),
            "forecast_policy": (
                "project forecasts use the canonical validation-momentum model; "
                "portfolio horizons sum usable project velocities and assume "
                "parallel work"
            ),
            "trend_policy": (
                "a single active trend is reported directly; disagreeing active "
                "project trends produce MIXED"
            ),
        },
    }


__all__ = [
    "PORTFOLIO_MOMENTUM_MODEL",
    "PORTFOLIO_TREND_MIXED",
    "PROJECT_STATUS_COMPLETE",
    "PROJECT_STATUS_NEEDS_ATTENTION",
    "PROJECT_STATUS_NO_ASSUMPTIONS",
    "PROJECT_STATUS_NO_EVIDENCE",
    "PROJECT_STATUS_ON_TRACK",
    "build_portfolio_validation_momentum",
]
