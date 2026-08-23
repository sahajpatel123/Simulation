"""
Pydantic schemas for the validation risk-map endpoint
``GET /api/v1/projects/{project_id}/validation-risk-map``.

The verdicts, quality, and staleness endpoints answer per-assumption
questions; this map answers the portfolio question: *which area of the
business model carries the weakest validation story right now?*
Assumptions are grouped by their category (pricing, demand, trust, …)
and each group is ranked by a transparent risk score combining killed
verdicts, self-contradicting records, untested claims, and low-trust
evidence.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RiskCategoryOut(BaseModel):
    """One assumption category's validation-risk rollup."""

    category: str
    total_assumptions: int = Field(default=0, ge=0)
    tested_count: int = Field(default=0, ge=0)
    untested_count: int = Field(default=0, ge=0)
    on_track_count: int = Field(default=0, ge=0)
    killed_count: int = Field(default=0, ge=0)
    inconsistent_count: int = Field(default=0, ge=0)
    unjudged_count: int = Field(default=0, ge=0)
    mean_quality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Mean evidence quality across the category's tested "
        "assumptions; None when nothing is tested yet.",
    )
    quality_label: str | None = None
    weakest_assumption_id: int | None = None
    weakest_assumption_text: str = ""
    weakest_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Weighted share of at-risk assumptions in the "
        "category; see meta.risk_weights.",
    )


class ValidationRiskMapOut(BaseModel):
    """Full response for the validation risk-map endpoint."""

    project_id: int
    category_count: int = Field(default=0, ge=0)
    total_assumptions: int = Field(default=0, ge=0)
    tested_count: int = Field(default=0, ge=0)
    untested_count: int = Field(default=0, ge=0)
    on_track_count: int = Field(default=0, ge=0)
    killed_count: int = Field(default=0, ge=0)
    inconsistent_count: int = Field(default=0, ge=0)
    riskiest_category: str | None = Field(
        default=None,
        description="Name of the highest-risk category; None when the "
        "project has no assumptions yet.",
    )
    categories: list[RiskCategoryOut] = Field(
        default_factory=list,
        description="Highest risk score first.",
    )
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RiskCategoryOut",
    "ValidationRiskMapOut",
]
