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


__all__ = [
    "WhatIfAssumption",
    "WhatIfRequest",
    "StageImpact",
    "WhatIfRecommendation",
    "WhatIfOut",
]
