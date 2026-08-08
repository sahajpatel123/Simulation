"""
Pydantic schemas for the assumption-postmortem digest endpoint
``GET /api/v1/simulations/{id}/assumption-postmortem``.

The digest connects the founder-outcome learning layer to the assumption
layer: for a completed simulation with a recorded actual conversion rate,
it scores each project assumption by ``sensitivity weight × |predicted −
actual|`` so the founder can see which core assumptions reality most likely
invalidated and which ones the launch validated.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VERDICT_VALIDATED: str = "VALIDATED"
VERDICT_MIXED: str = "MIXED"
VERDICT_INVALIDATED: str = "INVALIDATED"


class AssumptionPostmortemItem(BaseModel):
    """One assumption with its postmortem verdict and score."""

    assumption_id: int | None = None
    text: str
    category: str | None = None
    sensitivity: str = "MEDIUM"
    impact_score: float = 0.0
    invalidation_score: float = Field(default=0.0, ge=0.0, le=1.0)
    verdict: str = VERDICT_INSUFFICIENT_DATA
    reason: str = ""


class AssumptionPostmortemSummary(BaseModel):
    """Aggregate rollup of the postmortem digest."""

    total_assumptions: int = 0
    invalidated_count: int = 0
    validated_count: int = 0
    insufficient_count: int = 0
    top_invalidated: list[AssumptionPostmortemItem] = Field(
        default_factory=list
    )


class AssumptionPostmortemOut(BaseModel):
    """Full assumption postmortem payload for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    predicted_conversion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    actual_conversion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    conversion_delta: float | None = Field(default=None)  # predicted - actual
    outcome_source: str = "NONE"
    verdict: str = VERDICT_INSUFFICIENT_DATA
    summary: AssumptionPostmortemSummary = Field(
        default_factory=AssumptionPostmortemSummary
    )
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VERDICT_INSUFFICIENT_DATA",
    "VERDICT_INVALIDATED",
    "VERDICT_MIXED",
    "VERDICT_VALIDATED",
    "AssumptionPostmortemItem",
    "AssumptionPostmortemOut",
    "AssumptionPostmortemSummary",
]
