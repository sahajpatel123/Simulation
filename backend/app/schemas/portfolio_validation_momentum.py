"""Schemas for the authenticated user's validation-momentum digest.

``GET /users/me/validation-momentum`` brings the project-level validation
forecast into one portfolio view.  It keeps each project's signal visible
while adding a parallel-workload rollup and a deterministic next-focus
ordering for founders managing more than one idea.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PortfolioValidationMomentumProjectOut(BaseModel):
    """One owned project in recommended validation-focus order."""

    project_id: int = Field(default=0, ge=0)
    project_title: str = ""
    rank: int = Field(default=0, ge=0)
    status: str = "NEEDS_ATTENTION"
    trend: str = "NO_EVIDENCE"
    total_assumptions: int = Field(default=0, ge=0)
    total_evidence_rows: int = Field(default=0, ge=0)
    assumptions_with_evidence: int = Field(default=0, ge=0)
    de_risked_count: int = Field(default=0, ge=0)
    challenged_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    evidence_coverage_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_velocity_per_week: float | None = Field(default=None, ge=0.0)
    de_risk_velocity_per_week: float | None = Field(default=None, ge=0.0)
    remaining_for_coverage: int = Field(default=0, ge=0)
    remaining_for_target: int = Field(default=0, ge=0)
    weeks_to_full_coverage: float | None = Field(default=None, ge=0.0)
    weeks_to_de_risked_target: float | None = Field(default=None, ge=0.0)
    latest_evidence_at: datetime | None = None
    confident: bool = False
    focus_reason: str = ""


class PortfolioValidationMomentumSummaryOut(BaseModel):
    """Cross-project totals and parallel validation forecast."""

    project_count: int = Field(default=0, ge=0)
    projects_with_evidence: int = Field(default=0, ge=0)
    projects_without_evidence: int = Field(default=0, ge=0)
    projects_needing_attention: int = Field(default=0, ge=0)
    projects_complete: int = Field(default=0, ge=0)
    total_assumptions: int = Field(default=0, ge=0)
    total_evidence_rows: int = Field(default=0, ge=0)
    assumptions_with_evidence: int = Field(default=0, ge=0)
    de_risked_count: int = Field(default=0, ge=0)
    challenged_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    evidence_coverage_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_velocity_per_week: float | None = Field(default=None, ge=0.0)
    de_risk_velocity_per_week: float | None = Field(default=None, ge=0.0)
    target_de_risked_pct: float = Field(default=1.0, ge=0.5, le=1.0)
    remaining_for_coverage: int = Field(default=0, ge=0)
    remaining_for_target: int = Field(default=0, ge=0)
    weeks_to_full_coverage: float | None = Field(default=None, ge=0.0)
    weeks_to_de_risked_target: float | None = Field(default=None, ge=0.0)
    portfolio_trend: str = "NO_EVIDENCE"
    focus_project_id: int | None = Field(default=None, ge=0)
    focus_project_title: str | None = None
    focus_reason: str = ""
    insights: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class PortfolioValidationMomentumOut(BaseModel):
    """Response from ``GET /users/me/validation-momentum``."""

    user_id: int = Field(default=0, ge=0)
    generated_at: datetime
    summary: PortfolioValidationMomentumSummaryOut
    projects: list[PortfolioValidationMomentumProjectOut] = Field(
        default_factory=list
    )
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "PortfolioValidationMomentumOut",
    "PortfolioValidationMomentumProjectOut",
    "PortfolioValidationMomentumSummaryOut",
]
