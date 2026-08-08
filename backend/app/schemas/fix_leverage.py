"""
Pydantic schemas for the fix-leverage conversion projection endpoint
``GET /api/v1/simulations/{id}/fix-leverage``.

The projection answers one founder question that the domain-finding list and
the action plan do not answer directly: *if I actually fix the top findings,
what would my conversion rate become?* It reuses the persisted domain
findings plus the funnel counts, maps each finding to the forward Markov
transition it would improve, and returns a deterministic, capped projection.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FixLeverageFinding(BaseModel):
    """One domain finding mapped to a forward funnel transition."""

    finding: str = ""
    architect_name: str = ""
    metric_affected: str = ""
    recommended_action: str = ""
    severity: str = "INFO"
    affected_transition: str | None = None
    conversion_impact: float = Field(default=0.0, ge=0.0)
    projected_uplift: float = Field(default=0.0, ge=0.0)
    cluster_id: str = ""
    cluster_name: str = ""


class FixLeverageSummary(BaseModel):
    """Aggregate rollup for the fix-leverage projection."""

    total_findings: int = 0
    actionable_findings: int = 0
    unmapped_findings: int = 0
    transitions_improved: list[str] = Field(default_factory=list)
    verdict: str = "INSUFFICIENT_DATA"


class FixLeverageOut(BaseModel):
    """Response payload for ``GET /simulations/{id}/fix-leverage``."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    baseline_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    projected_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    absolute_lift: float | None = Field(default=None)
    relative_lift_pct: float | None = Field(default=None)
    findings: list[FixLeverageFinding] = Field(default_factory=list)
    summary: FixLeverageSummary = Field(default_factory=FixLeverageSummary)
    meta: dict = Field(default_factory=dict)


__all__ = [
    "FixLeverageFinding",
    "FixLeverageOut",
    "FixLeverageSummary",
]
