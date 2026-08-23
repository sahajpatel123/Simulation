"""
Pydantic schemas for the validation-sprint scheduler endpoint
``GET /api/v1/simulations/{id}/validation-experiment-plan/schedule``.

The experiment planner answers *what to run*; real founders also have a
calendar and a wallet. The scheduler re-fits the planned experiments into an
explicit time and cost envelope: which ones make the cut (sequenced
back-to-back), which are deferred and why, and how much of the available
de-risking survives the constraint.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.validation_experiment import (
    COST_TIER_LITERAL,
    ValidationExperiment,
)


class ScheduledExperiment(ValidationExperiment):
    """A planned experiment that fits inside the sprint envelope."""

    scheduled_day: int = Field(default=1, ge=1)  # 1-based start day
    finishes_by_day: int = Field(default=1, ge=1)  # inclusive last day


class DeferredExperiment(BaseModel):
    """A planned experiment that did not fit, with why it was cut."""

    assumption_text: str = ""
    method_label: str = ""
    cost_tier: COST_TIER_LITERAL = "FREE"
    estimated_duration_days: int = Field(default=7, ge=1, le=90)
    validation_roi: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class ValidationSprintSummary(BaseModel):
    """Aggregate of the constrained schedule."""

    planned_count: int = Field(default=0, ge=0)
    scheduled_count: int = Field(default=0, ge=0)
    deferred_count: int = Field(default=0, ge=0)
    max_days: int = Field(default=0, ge=0)
    budget_tier: COST_TIER_LITERAL = "FREE"
    days_used: int = Field(default=0, ge=0)
    days_remaining: int = Field(default=0, ge=0)
    free_count: int = Field(default=0, ge=0)
    low_cost_count: int = Field(default=0, ge=0)
    medium_cost_count: int = Field(default=0, ge=0)
    coverage_retained: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of the plan's total validation-ROI kept after the "
            "constraint; null when the plan had no experiments at all."
        ),
    )
    top_experiment: str = ""


class ValidationSprintScheduleOut(BaseModel):
    """Full response for the validation-sprint schedule endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    summary: ValidationSprintSummary
    experiments: list[ScheduledExperiment] = Field(default_factory=list)
    deferred: list[DeferredExperiment] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DeferredExperiment",
    "ScheduledExperiment",
    "ValidationSprintScheduleOut",
    "ValidationSprintSummary",
]
