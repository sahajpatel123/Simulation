"""
Pydantic schemas for the authenticated user's portfolio analytics rollup.

The route ``GET /analytics/me/portfolio`` returns ``UserPortfolioOut`` so
the frontend can render a single dashboard view across the user's projects.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatusBreakdown(BaseModel):
    """Counts of items in each status bucket."""

    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class ConversionDistribution(BaseModel):
    """Aggregate statistics of the latest completed simulation per project."""

    project_count: int = 0
    min: float | None = None
    median: float | None = None
    mean: float | None = None
    max: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class FailureDomainCount(BaseModel):
    architect_name: str
    count: int


class StressTestCoverage(BaseModel):
    total: int = 0
    completed: int = 0
    with_kill_shots: int = 0
    with_partial_kill_shots: int = 0
    overall_risk_breakdown: dict[str, int] = Field(default_factory=dict)


class RecentProject(BaseModel):
    id: int
    title: str
    status: str
    updated_at: str | None = None
    has_completed_simulation: bool = False
    latest_conversion_rate: float | None = None
    primary_failure_domain: str | None = None


class UserPortfolioOut(BaseModel):
    """Aggregate dashboard view for the authenticated user."""

    user_id: int
    projects: StatusBreakdown = Field(default_factory=StatusBreakdown)
    simulations: StatusBreakdown = Field(default_factory=StatusBreakdown)
    conversion_distribution: ConversionDistribution = Field(
        default_factory=ConversionDistribution
    )
    primary_failure_domains: list[FailureDomainCount] = Field(default_factory=list)
    stress_test_coverage: StressTestCoverage = Field(
        default_factory=StressTestCoverage
    )
    outcome_coverage: dict[str, int] = Field(
        default_factory=dict,
        description="Keys: 'simulations_total', 'with_outcome'.",
    )
    recent_projects: list[RecentProject] = Field(default_factory=list)
    generated_at: str = ""


__all__ = [
    "StatusBreakdown",
    "ConversionDistribution",
    "FailureDomainCount",
    "StressTestCoverage",
    "RecentProject",
    "UserPortfolioOut",
]
