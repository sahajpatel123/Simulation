"""Pydantic schemas for portfolio outcome-feedback coverage by product type.

``GET /users/me/outcome-gaps/product-types`` answers a question the
per-project and portfolio gap digests cannot: **across all of my projects,
which product categories have the weakest real-world feedback loop?**
Each detected product type is rolled up with coverage rate, learning-eligible
gaps, stale high-priority gaps, the oldest open gap, an urgency distribution,
and the mean prediction error on already-scored runs, sorted weakest-first so
the founder knows exactly where to spend their next outcome-submission effort.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProductTypeOutcomeGapRow(BaseModel):
    """One product type's outcome-feedback coverage rollup."""

    product_type: str
    total_completed: int = Field(default=0, ge=0)
    scored: int = Field(default=0, ge=0)
    unscored: int = Field(default=0, ge=0)
    coverage_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    learning_eligible_unscored: int = Field(default=0, ge=0)
    high_priority_unscored: int = Field(default=0, ge=0)
    oldest_unscored_age_days: int | None = Field(default=None, ge=0)
    urgency_counts: dict[str, int] = Field(default_factory=dict)
    mean_absolute_gap: float | None = Field(default=None, ge=0.0)
    scored_with_prediction: int = Field(default=0, ge=0)
    recommendation: str = ""


class ProductTypeOutcomeGapsSummary(BaseModel):
    """Portfolio rollup of outcome-feedback gaps by product type."""

    product_type_count: int = Field(default=0, ge=0)
    project_count: int = Field(default=0, ge=0)
    total_completed: int = Field(default=0, ge=0)
    scored: int = Field(default=0, ge=0)
    unscored: int = Field(default=0, ge=0)
    coverage_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    learning_eligible_unscored: int = Field(default=0, ge=0)
    high_priority_unscored: int = Field(default=0, ge=0)
    oldest_unscored_age_days: int | None = Field(default=None, ge=0)
    narrative: str = ""


class ProductTypeOutcomeGapsOut(BaseModel):
    """Response from ``GET /users/me/outcome-gaps/product-types``."""

    user_id: int = Field(default=0, ge=0)
    generated_at: datetime
    summary: ProductTypeOutcomeGapsSummary
    product_types: list[ProductTypeOutcomeGapRow] = Field(default_factory=list)
    learning_eligible_only: bool = False


__all__ = [
    "ProductTypeOutcomeGapRow",
    "ProductTypeOutcomeGapsOut",
    "ProductTypeOutcomeGapsSummary",
]
