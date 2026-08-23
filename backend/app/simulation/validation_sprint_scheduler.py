"""
Budget-constrained validation sprint scheduler.

``build_validation_experiment_plan`` sequences every experiment worth
running but assumes an unconstrained founder. Real founders have a
calendar and a wallet, so this module re-fits the plan to an explicit
envelope — ``max_days`` of sequential execution and a ``budget_tier``
ceiling — keeping as much de-risking as the constraint allows.

Selection is deterministic greedy first-fit in the plan's existing
validation-ROI order: an experiment is scheduled when its cost tier clears
the ceiling and it still fits in the remaining days; anything else is
deferred with a founder-readable reason. ``coverage_retained`` reports how
much of the plan's total validation-ROI survives the cut.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.validation_experiment import (
    COST_TIER_LITERAL,
    ValidationExperiment,
    ValidationExperimentPlanOut,
)
from app.schemas.validation_sprint import (
    DeferredExperiment,
    ScheduledExperiment,
    ValidationSprintScheduleOut,
    ValidationSprintSummary,
)

COST_RANK: dict[str, int] = {"FREE": 0, "LOW": 1, "MEDIUM": 2}


def _cost_rank(tier: str) -> int:
    try:
        return COST_RANK[tier]
    except KeyError:
        raise ValueError(
            f"unknown cost tier {tier!r}; expected FREE/LOW/MEDIUM"
        ) from None


def _deferred(exp: ValidationExperiment, reason: str) -> DeferredExperiment:
    return DeferredExperiment(
        assumption_text=exp.assumption_text,
        method_label=exp.method_label,
        cost_tier=exp.cost_tier,
        estimated_duration_days=exp.estimated_duration_days,
        validation_roi=exp.validation_roi,
        reason=reason,
    )


def _build_narrative(
    summary: ValidationSprintSummary,
    scheduled: list[ScheduledExperiment],
) -> str:
    if summary.planned_count == 0:
        return (
            "No experiments were planned for this simulation, so there is "
            "nothing to fit into a sprint window."
        )
    if not scheduled:
        return (
            f"A {summary.max_days}-day sprint at a {summary.budget_tier.lower()} "
            f"budget fits none of the {summary.planned_count} planned "
            "experiments. Raise the day budget or the cost ceiling — each "
            "deferred experiment carries the reason it was cut."
        )
    top = scheduled[0]
    coverage = (
        f"{summary.coverage_retained:.0%}"
        if summary.coverage_retained is not None
        else "unknown share of"
    )
    window = (
        f"{summary.max_days}-day sprint at a "
        f"{summary.budget_tier.lower()} budget"
    )
    if summary.max_parallel > 1:
        window += f" on {summary.max_parallel} parallel tracks"
    text = (
        f"{summary.scheduled_count} of {summary.planned_count} planned "
        f"experiments fit a {window}, retaining {coverage} of the "
        f"available de-risking. Start with {top.method_label.lower()} for "
        f"'{top.assumption_text[:80]}' (days {top.scheduled_day}-"
        f"{top.finishes_by_day})."
    )
    if summary.deferred_count:
        text += (
            f" {summary.deferred_count} deferred — each carries the reason "
            "it was cut."
        )
    else:
        text += " Everything planned made the cut."
    return text


def schedule_validation_sprint(
    plan: ValidationExperimentPlanOut,
    *,
    max_days: int = 14,
    budget_tier: COST_TIER_LITERAL = "LOW",
    max_parallel: int = 1,
) -> ValidationSprintScheduleOut:
    """
    Fit a validation experiment plan into a real calendar and budget.

    Experiments are considered in the plan's ROI order. Each is scheduled
    when its cost tier is at or under ``budget_tier`` and it fits the days
    left in ``max_days``; otherwise it is deferred with a founder-readable
    reason. ``max_parallel`` concurrent tracks let founders overlap tests
    (a landing page collects signups while interviews run); each experiment
    takes the track that finishes it earliest. Returns the sequenced
    schedule, the deferred list, and how much of the plan's total
    validation-ROI survived.
    """
    limit_days = max(1, int(max_days))
    lane_count = max(1, int(max_parallel))
    ceiling_rank = _cost_rank(budget_tier)

    candidates = list(plan.experiments)
    total_roi = sum(exp.validation_roi for exp in candidates)

    scheduled: list[ScheduledExperiment] = []
    deferred: list[DeferredExperiment] = []
    # Next free day per parallel track; 0 means the track starts on day 1.
    lanes: list[int] = [0] * lane_count

    for exp in candidates:
        if _cost_rank(exp.cost_tier) > ceiling_rank:
            deferred.append(
                _deferred(
                    exp,
                    reason=(
                        f"cost tier {exp.cost_tier.lower()} exceeds the "
                        f"{budget_tier.lower()} budget ceiling"
                    ),
                )
            )
            continue
        feasible = [
            (lane_free + exp.estimated_duration_days, i)
            for i, lane_free in enumerate(lanes)
            if limit_days - lane_free >= exp.estimated_duration_days
        ]
        if not feasible:
            soonest_free = min(lanes)
            remaining = limit_days - soonest_free
            deferred.append(
                _deferred(
                    exp,
                    reason=(
                        f"needs {exp.estimated_duration_days} days but only "
                        f"{remaining} remain in the {limit_days}-day sprint"
                        if remaining < exp.estimated_duration_days
                        else (
                            f"needs {exp.estimated_duration_days} free days "
                            f"on one track but all {lane_count} tracks are "
                            f"busy until day {soonest_free + 1}"
                        )
                    ),
                )
            )
            continue
        end, lane_index = min(feasible)
        start = lanes[lane_index] + 1
        lanes[lane_index] = end
        scheduled.append(
            ScheduledExperiment(
                **exp.model_dump(),
                scheduled_day=start,
                finishes_by_day=end,
            )
        )

    day_cursor = max(lanes) if scheduled else 0

    kept_roi = sum(exp.validation_roi for exp in scheduled)
    coverage = kept_roi / total_roi if total_roi > 0 else None

    counts = {"FREE": 0, "LOW": 0, "MEDIUM": 0}
    for exp in scheduled:
        counts[exp.cost_tier] += 1

    summary = ValidationSprintSummary(
        planned_count=len(candidates),
        scheduled_count=len(scheduled),
        deferred_count=len(deferred),
        max_days=limit_days,
        budget_tier=budget_tier,
        max_parallel=lane_count,
        days_used=day_cursor,
        days_remaining=limit_days - day_cursor,
        free_count=counts["FREE"],
        low_cost_count=counts["LOW"],
        medium_cost_count=counts["MEDIUM"],
        coverage_retained=coverage,
        top_experiment=scheduled[0].method_label if scheduled else "",
    )

    return ValidationSprintScheduleOut(
        simulation_id=plan.simulation_id,
        project_id=plan.project_id,
        status=plan.status,
        summary=summary,
        experiments=scheduled,
        deferred=deferred,
        narrative=_build_narrative(summary, scheduled),
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "validation_sprint_scheduler_v1",
            "constraint_semantics": (
                "days run across up to max_parallel tracks; each experiment "
                "takes the track that finishes it earliest"
            ),
            "selection": "greedy first-fit in validation-ROI order",
            "coverage_definition": (
                "sum(validation_roi of scheduled) / sum(validation_roi of all planned)"
            ),
            "source_plan_model": plan.meta.get("model", ""),
        },
    )


__all__ = [
    "COST_RANK",
    "schedule_validation_sprint",
]
