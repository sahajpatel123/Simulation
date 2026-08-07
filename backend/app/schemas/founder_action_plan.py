"""
Pydantic schemas for the founder action plan endpoint
``GET /api/v1/simulations/{id}/founder-action-plan``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


EFFORT_LOW: str = "LOW"
EFFORT_MEDIUM: str = "MEDIUM"
EFFORT_HIGH: str = "HIGH"


class ActionPlanItem(BaseModel):
    """One ranked, founder-facing action with effort and impact estimate."""

    priority: int = 0
    title: str
    summary: str = ""
    domain: str = ""
    stage: str = ""
    metric_affected: str = ""
    source: str = ""  # "DOMAIN_FINDING" | "FUNNEL_BOTTLENECK"
    severity: str = "INFO"
    effort: str = EFFORT_LOW  # LOW | MEDIUM | HIGH
    quick_win_score: float = 0.0
    estimated_conversion_impact: float = Field(default=0.0, ge=0.0)
    recommended_action: str = ""
    related_cluster_ids: list[str] = Field(default_factory=list)


class ActionPlanSummary(BaseModel):
    """Aggregate rollup of the action plan."""

    total_actions: int = 0
    total_critical: int = 0
    total_warning: int = 0
    quick_win_count: int = 0
    estimated_total_conversion_impact: float = Field(default=0.0, ge=0.0)
    verdict: str = "INSUFFICIENT_DATA"


class FounderActionPlanOut(BaseModel):
    """Ranked founder action plan for a completed simulation run."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    headline_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_bottleneck: str | None = None
    actions: list[ActionPlanItem] = Field(default_factory=list)
    summary: ActionPlanSummary = Field(default_factory=ActionPlanSummary)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ActionPlanItem",
    "ActionPlanSummary",
    "EFFORT_HIGH",
    "EFFORT_LOW",
    "EFFORT_MEDIUM",
    "FounderActionPlanOut",
]
