"""Pydantic schemas for the portfolio-level outcome-feedback gaps digest.

``GET /users/me/outcome-gaps`` answers a question the per-project digest
cannot: **across all of my projects, which completed simulation runs still
need real-world outcome feedback, and where is the calibration layer waiting?**
Each owned project is rolled up (coverage rate, learning-eligible gaps,
high-priority stale gaps) and the unscored runs are listed oldest first.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.outcome_gaps import SimulationOutcomeGapItem


class PortfolioOutcomeGapProject(BaseModel):
    """One project's rollup inside the portfolio gaps digest."""

    project_id: int = Field(default=0, ge=0)
    total_completed: int = Field(default=0, ge=0)
    scored: int = Field(default=0, ge=0)
    unscored: int = Field(default=0, ge=0)
    coverage_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    learning_eligible_unscored: int = Field(default=0, ge=0)
    high_priority_unscored: int = Field(default=0, ge=0)
    oldest_unscored_age_days: int | None = Field(default=None, ge=0)


class PortfolioOutcomeGapsSummary(BaseModel):
    """Portfolio rollup of outcome-feedback gaps."""

    project_count: int = Field(default=0, ge=0)
    projects_with_gaps: int = Field(default=0, ge=0)
    total_completed: int = Field(default=0, ge=0)
    scored: int = Field(default=0, ge=0)
    unscored: int = Field(default=0, ge=0)
    coverage_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    learning_eligible_unscored: int = Field(default=0, ge=0)
    high_priority_unscored: int = Field(default=0, ge=0)
    oldest_unscored_age_days: int | None = Field(default=None, ge=0)
    narrative: str = ""


class PortfolioOutcomeGapItem(SimulationOutcomeGapItem):
    """One unscored simulation inside the portfolio digest."""

    project_id: int = Field(default=0, ge=0)


class PortfolioOutcomeGapsOut(BaseModel):
    """Response from ``GET /users/me/outcome-gaps``."""

    user_id: int = Field(default=0, ge=0)
    generated_at: datetime
    summary: PortfolioOutcomeGapsSummary
    projects: list[PortfolioOutcomeGapProject] = Field(default_factory=list)
    items: list[PortfolioOutcomeGapItem] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1)
    has_more: bool = False
    learning_eligible_only: bool = False


__all__ = [
    "PortfolioOutcomeGapItem",
    "PortfolioOutcomeGapProject",
    "PortfolioOutcomeGapsOut",
    "PortfolioOutcomeGapsSummary",
]
