"""
Pydantic schemas for the what-if scenario simulator endpoint
``POST /api/v1/simulations/{id}/what-if``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WhatIfAssumption(BaseModel):
    """A single assumption to add or modify in the what-if scenario."""

    text: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Assumption text — keywords are matched against Markov rules",
    )
    sensitivity: str = Field(
        default="MEDIUM",
        description="CRITICAL | HIGH | MEDIUM | LOW — controls adjustment magnitude",
    )
    impact_score: float = Field(
        default=5.0,
        ge=0.0,
        le=10.0,
        description="0–10 scale; higher = stronger transition adjustment",
    )


class WhatIfRequest(BaseModel):
    """Body for the what-if scenario simulator."""

    assumptions: list[WhatIfAssumption] = Field(
        default_factory=list,
        max_length=20,
        description="Additional assumptions to apply on top of the simulation's existing assumptions",
    )
    override_price_sensitivity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override the environment's price_sensitivity (0.0–1.0)",
    )
    override_market_maturity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override the environment's market_maturity (0.0–1.0)",
    )


class StageImpact(BaseModel):
    """Per-stage transition impact from the what-if assumptions."""

    stage: str
    transition: str
    base_rate: float = 0.0
    projected_rate: float = 0.0
    delta: float = 0.0
    affected_by: list[str] = Field(default_factory=list)


class WhatIfRecommendation(BaseModel):
    """A recommendation generated from the what-if analysis."""

    priority: int
    title: str
    rationale: str
    estimated_lift: float = 0.0
    affected_stages: list[str] = Field(default_factory=list)


class WhatIfOut(BaseModel):
    """Full response for the what-if scenario simulator."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    base_conversion_rate: float = 0.0
    projected_conversion_rate: float = 0.0
    conversion_delta: float = 0.0
    conversion_delta_pct: float = 0.0
    base_revenue_per_1000: float = 0.0
    projected_revenue_per_1000: float = 0.0
    stage_impacts: list[StageImpact] = Field(default_factory=list)
    recommendations: list[WhatIfRecommendation] = Field(default_factory=list)
    assumptions_applied: list[WhatIfAssumption] = Field(default_factory=list)
    env_overrides: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """Return a compact summary suitable for logging or compact UI display."""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "base_conversion_rate": self.base_conversion_rate,
            "projected_conversion_rate": self.projected_conversion_rate,
            "conversion_delta": self.conversion_delta,
            "conversion_delta_pct": self.conversion_delta_pct,
            "dominant_direction": self.meta.get("dominant_direction"),
            "sensitivity_label": self.meta.get("sensitivity_label"),
            "matched_keyword_categories": list(
                self.meta.get("matched_keyword_categories", [])
            ),
        }

    def to_log_line(self) -> str:
        """Return a compact one-line log string describing the scenario."""
        direction = self.meta.get("dominant_direction", "NEUTRAL")
        sensitivity = self.meta.get("sensitivity_label", "NONE")
        return (
            f"what-if sim={self.simulation_id} "
            f"base={self.base_conversion_rate:.4f} "
            f"projected={self.projected_conversion_rate:.4f} "
            f"delta_pct={self.conversion_delta_pct:+.2f}% "
            f"direction={direction} "
            f"sensitivity={sensitivity}"
        )

    def has_positive_delta(self) -> bool:
        """Return True when conversion_delta is strictly positive."""
        return self.conversion_delta > 0.0

    def has_negative_delta(self) -> bool:
        """Return True when conversion_delta is strictly negative."""
        return self.conversion_delta < 0.0

    def is_neutral(self) -> bool:
        """Return True when conversion_delta is zero (within float tolerance)."""
        return abs(self.conversion_delta) < 1e-9

    def __str__(self) -> str:
        return self.to_log_line()


class WhatIfSummaryCategory(BaseModel):
    """One row of the top-categories table in ``WhatIfSummary``."""

    category: str
    count: int


class WhatIfSummary(BaseModel):
    """Aggregate view of multiple ``WhatIfOut`` scenarios for compare-scenarios UI."""

    scenario_count: int = 0
    avg_delta: float = 0.0
    best_delta: float = 0.0
    worst_delta: float = 0.0
    direction_breakdown: dict[str, int] = Field(default_factory=dict)
    top_categories: list[WhatIfSummaryCategory] = Field(default_factory=list)


class WhatIfDiff(BaseModel):
    """Pairwise comparison of two ``WhatIfOut`` scenarios."""

    base_simulation_id: int
    other_simulation_id: int
    base_new_assumption_count: int = 0
    other_new_assumption_count: int = 0
    base_delta: float = 0.0
    other_delta: float = 0.0
    delta_difference: float = 0.0
    shared_keyword_categories: list[str] = Field(default_factory=list)
    base_only_categories: list[str] = Field(default_factory=list)
    other_only_categories: list[str] = Field(default_factory=list)


__all__ = [
    "WhatIfAssumption",
    "WhatIfRequest",
    "StageImpact",
    "WhatIfRecommendation",
    "WhatIfOut",
    "WhatIfSummary",
    "WhatIfSummaryCategory",
    "WhatIfDiff",
]
