"""
Pydantic schemas for the assumption-recovery-plan endpoint
``GET /api/v1/projects/{project_id}/assumption-recovery-plan``.

The evidence-verdicts scorecard says *which* assumptions died or
contradict their own records; the recovery planner answers the founder's
next question — *how do I get this idea back on track?* Each killed or
inconsistent assumption gets ordered, deterministic recovery plays: a
reframed hypothesis plus the concrete re-test (method, cost tier,
duration, sample target, success bar) pulled from the same METHOD_SPECS
table the experiment planner uses.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.validation_experiment import (
    COST_TIER_LITERAL,
    METHOD_ID_LITERAL,
)

RECOVERY_TRIGGER_LITERAL = Literal[
    "KILLED",
    "INCONSISTENT_PASS",
    "INCONSISTENT_FAIL",
]

RECOVERY_THEME_LITERAL = Literal[
    "pricing",
    "demand",
    "trust",
    "competition",
    "usability",
    "retention",
    "general",
]


class RecoveryAction(BaseModel):
    """One concrete recovery play for a failed or inconsistent claim."""

    order: int = Field(default=1, ge=1)
    title: str = ""
    rationale: str = ""
    method: METHOD_ID_LITERAL = "USER_INTERVIEWS"
    method_label: str = ""
    cost_tier: COST_TIER_LITERAL = "FREE"
    estimated_duration_days: int = Field(default=7, ge=1, le=90)
    sample_target: str = ""
    success_metric: str = ""
    success_threshold: str = ""


class RecoveryRow(BaseModel):
    """One attention-worthy assumption with its ordered recovery plays."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    trigger: RECOVERY_TRIGGER_LITERAL = "KILLED"
    theme: RECOVERY_THEME_LITERAL = "general"
    actions: list[RecoveryAction] = Field(default_factory=list)
    fastest_path_days: int = Field(default=0, ge=0)
    cheapest_action_title: str = ""


class RecoveryPlanOut(BaseModel):
    """Full response for the assumption-recovery-plan endpoint."""

    project_id: int
    total_assumptions: int = Field(default=0, ge=0)
    attention_count: int = Field(default=0, ge=0)
    killed_count: int = Field(default=0, ge=0)
    inconsistent_count: int = Field(default=0, ge=0)
    theme_counts: dict[str, int] = Field(default_factory=dict)
    rows: list[RecoveryRow] = Field(
        default_factory=list,
        description=(
            "Killed assumptions first (most recovery actions first), then "
            "inconsistent ones."
        ),
    )
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RECOVERY_THEME_LITERAL",
    "RECOVERY_TRIGGER_LITERAL",
    "RecoveryAction",
    "RecoveryPlanOut",
    "RecoveryRow",
]
