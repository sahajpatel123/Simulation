"""
Pydantic schemas for the launch-checklist read
``GET /api/v1/simulations/{id}/launch-checklist``.

The endpoint answers the founder's "are these simulation signals strong
enough to act on before launch?" question by running a deterministic
checklist over a completed run's persisted results, signal quality,
cluster coverage, assumptions and funnel sanity. Output is a 0..1
``readiness_score`` with a READY / NEEDS_WORK / NOT_READY /
INSUFFICIENT_DATA verdict plus itemized checks and recommendations.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


STATUS_LITERAL = Literal["PASS", "WARN", "FAIL", "INFO", "SKIP"]
VERDICT_LITERAL = Literal[
    "READY",
    "NEEDS_WORK",
    "NOT_READY",
    "INSUFFICIENT_DATA",
]


class LaunchChecklistItem(BaseModel):
    """One readiness check in the launch checklist."""

    id: str
    category: str = "data"
    label: str = ""
    status: STATUS_LITERAL = "INFO"
    detail: str = ""
    weight: float = Field(default=1.0, ge=0.0)
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class LaunchChecklistSummary(BaseModel):
    """Aggregate counts for the launch checklist."""

    total_items: int = Field(default=0, ge=0)
    evaluated_items: int = Field(default=0, ge=0)
    passed_items: int = Field(default=0, ge=0)
    warned_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    skipped_items: int = Field(default=0, ge=0)


class LaunchChecklistOut(BaseModel):
    """Full launch-checklist response for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    readiness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    verdict: VERDICT_LITERAL = "INSUFFICIENT_DATA"
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    visible_assumptions: int | None = None
    summary: LaunchChecklistSummary
    items: list[LaunchChecklistItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "LaunchChecklistItem",
    "LaunchChecklistOut",
    "LaunchChecklistSummary",
]
