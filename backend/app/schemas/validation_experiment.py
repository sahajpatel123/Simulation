"""
Pydantic schemas for the validation-experiment-planner endpoint
``GET /api/v1/simulations/{id}/validation-experiment-plan``.

The validation-ROI analysis says *which* assumption to de-risk first; the
planner turns that ranking into concrete, sequenced experiments a founder can
run this week — method, cost tier, duration, sample target, success metric,
and a go/no-go rule per assumption.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.validation_roi import (
    CONFIDENCE_TIER_LITERAL,
    ROI_TIER_LITERAL,
)

COST_TIER_LITERAL = Literal["FREE", "LOW", "MEDIUM"]

METHOD_ID_LITERAL = Literal[
    "LANDING_PAGE_SMOKE_TEST",
    "CONCIERGE_MVP",
    "WILLINGNESS_TO_PAY_SURVEY",
    "COMPETITIVE_DESK_RESEARCH",
    "PROTOTYPE_USABILITY_TEST",
    "PRE_ORDER_WAITLIST",
    "PAID_ACQUISITION_TEST",
    "USER_INTERVIEWS",
]


class ValidationExperiment(BaseModel):
    """A single concrete validation experiment for one assumption."""

    assumption_text: str = ""
    category: str = ""
    roi_tier: ROI_TIER_LITERAL = "LOW_VALUE"
    validation_roi: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_conversion_swing: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_tier: CONFIDENCE_TIER_LITERAL = "DESIGN_INTENT"
    method: METHOD_ID_LITERAL = "USER_INTERVIEWS"
    method_label: str = ""
    method_description: str = ""
    cost_tier: COST_TIER_LITERAL = "FREE"
    estimated_duration_days: int = Field(default=7, ge=1, le=90)
    sample_target: str = ""
    success_metric: str = ""
    success_threshold: str = ""
    go_no_go_rule: str = ""
    rationale: str = ""


class ValidationExperimentSummary(BaseModel):
    """Aggregate of the planned validation sprint."""

    experiment_count: int = Field(default=0, ge=0)
    validate_first_count: int = Field(default=0, ge=0)
    high_value_count: int = Field(default=0, ge=0)
    free_count: int = Field(default=0, ge=0)
    low_cost_count: int = Field(default=0, ge=0)
    medium_cost_count: int = Field(default=0, ge=0)
    sprint_days: int = Field(default=0, ge=0)  # parallel (max duration)
    sequential_days: int = Field(default=0, ge=0)  # run back-to-back
    budget_ceiling: COST_TIER_LITERAL = "FREE"
    top_experiment: str = ""


class ValidationExperimentPlanOut(BaseModel):
    """Full response for the validation-experiment-plan endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    baseline_conversion: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: ValidationExperimentSummary
    experiments: list[ValidationExperiment] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "COST_TIER_LITERAL",
    "METHOD_ID_LITERAL",
    "ValidationExperiment",
    "ValidationExperimentSummary",
    "ValidationExperimentPlanOut",
]
