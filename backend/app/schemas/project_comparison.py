"""Pydantic schemas for the project comparison endpoint.

``POST /api/v1/projects/compare`` accepts exactly two owned project IDs
and returns a side-by-side comparison of health, funnel, assumptions,
outcomes, and risk signals.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProjectCompareRequest(BaseModel):
    """Body for comparing two owned projects."""

    project_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Exactly two project IDs to compare side-by-side.",
    )

    @field_validator("project_ids")
    @classmethod
    def _unique_positive_ids(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("project_ids must be unique")
        if any(i <= 0 for i in value):
            raise ValueError("project_ids must be positive integers")
        return value


class ComparisonProjectRef(BaseModel):
    """One project's key metrics in a comparison."""

    project_id: int
    title: str = ""
    status: str = "DRAFT"
    health_score: int = 0
    health_verdict: str = "AT_RISK"
    simulation_count: int = 0
    latest_conversion_rate: float | None = None
    latest_confidence_score: float | None = None
    assumption_count: int = 0
    outcome_count: int = 0
    pending_decision_count: int = 0
    critical_finding_count: int = 0
    weak_link_count: int = 0
    brief_completed: bool = False
    primary_failure_domain: str | None = None
    product_type_detected: str | None = None


class ProjectComparisonDimension(BaseModel):
    """One row in the side-by-side comparison table."""

    dimension: str
    label: str
    higher_is_better: bool = True
    a: Any = None
    b: Any = None
    winner: str = "TIE"
    display_a: str = ""
    display_b: str = ""


class ProjectComparisonSummary(BaseModel):
    """Overall winner / verdict block for a project comparison."""

    winner_project_id: int | None = None
    winner_label: str = "TIE"
    verdict: str = "NEEDS_MORE_DATA"
    narrative: str = ""
    key_signals: list[dict[str, Any]] = Field(default_factory=list)


class ProjectComparisonOut(BaseModel):
    """Full response for ``POST /projects/compare``."""

    comparison_id: str
    projects: list[ComparisonProjectRef] = Field(default_factory=list)
    dimensions: list[ProjectComparisonDimension] = Field(default_factory=list)
    summary: ProjectComparisonSummary = Field(default_factory=ProjectComparisonSummary)
    generated_at: str = ""


__all__ = [
    "ProjectCompareRequest",
    "ComparisonProjectRef",
    "ProjectComparisonDimension",
    "ProjectComparisonSummary",
    "ProjectComparisonOut",
]
