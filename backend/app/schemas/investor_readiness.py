"""
Pydantic schemas for the investor-readiness digest
``GET /api/v1/simulations/{id}/investor-readiness``.

The endpoint consolidates six existing deterministic reads into one
investor-facing scorecard: market sizing, unit economics, retention,
competitive moat, launch readiness and simulation trust. Each pillar
carries a 0..100 score and a verdict; the digest combines the available
pillars into an overall investor score with strengths, risks and top
actions a founder can act on before a raise.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PILLAR_VERDICT_LITERAL = Literal[
    "STRONG",
    "MODERATE",
    "WEAK",
    "INSUFFICIENT_DATA",
]

INVESTOR_VERDICT_LITERAL = Literal[
    "INVESTMENT_GRADE",
    "RAISABLE",
    "PRE_SEED",
    "NOT_INVESTABLE",
    "INSUFFICIENT_DATA",
]


class InvestorPillar(BaseModel):
    """One scored pillar of the investor-readiness digest."""

    key: str
    label: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    verdict: PILLAR_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    summary: str = ""


class InvestorReadinessOut(BaseModel):
    """Full investor-readiness response for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    investor_score: int | None = Field(default=None, ge=0, le=100)
    verdict: INVESTOR_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    verdict_label: str = ""
    pillars: list[InvestorPillar] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    top_actions: list[str] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "InvestorPillar",
    "InvestorReadinessOut",
]
