"""
Pydantic schema for the founder-brief digest
``GET /api/v1/simulations/{id}/founder-brief``.

The endpoint consolidates the simulation quality gate, launch-readiness
checklist and market-sizing projection into one founder-facing digest:
headline conversion, trust score, readiness score, market sizing and
top recommendations.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


VERDICT_LITERAL = Literal[
    "READY",
    "NEEDS_WORK",
    "NOT_READY",
    "INSUFFICIENT_DATA",
]


class FounderBriefOut(BaseModel):
    """Full founder-brief response for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    headline_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    readiness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    verdict: VERDICT_LITERAL = "INSUFFICIENT_DATA"
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    visible_assumptions: int | None = None
    tam_customers: int = 0
    sam_customers: int = 0
    som_customers: int = 0
    annual_revenue: float = 0.0
    top_recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = ["FounderBriefOut"]
