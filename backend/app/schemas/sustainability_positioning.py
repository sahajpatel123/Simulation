"""
Pydantic schemas for the sustainability-positioning read
``GET /api/v1/simulations/{id}/sustainability-positioning``.

The endpoint exposes ``SustainabilityArchitect`` metrics as a founder-facing
ESG read: whether the brief makes sustainability claims, how much of the
covered market responds, the population-weighted conversion lift, per-cluster
response tiers, and the market-level greenwashing / premium-friction flags.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_STRONG: str = "STRONG"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_WEAK: str = "WEAK"
VERDICT_NOT_POSITIONED: str = "NOT_POSITIONED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_STRONG,
        VERDICT_MODERATE,
        VERDICT_WEAK,
        VERDICT_NOT_POSITIONED,
        VERDICT_INSUFFICIENT,
    }
)

TIER_HIGH: str = "HIGH_RESPONSE"
TIER_MODERATE: str = "MODERATE_RESPONSE"
TIER_LOW: str = "LOW_RESPONSE"
TIER_NO_SIGNAL: str = "NO_SIGNAL"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_HIGH, TIER_MODERATE, TIER_LOW, TIER_NO_SIGNAL}
)


class ClusterSustainabilityProfile(BaseModel):
    """One cluster's ESG-response profile from SustainabilityArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    sustainability_signal: float = 0.0
    esg_affinity: float = 0.0
    conversion_lift: float = 0.0
    green_premium_tolerance: float = 0.0
    premium_friction: float = 0.0
    claim_credibility: float = 0.0
    tier: str = TIER_NO_SIGNAL
    flags: list[str] = Field(default_factory=list)


class SustainabilityOpportunity(BaseModel):
    """One high-impact cluster to lead with when positioning on ESG."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_lift: float = 0.0
    esg_affinity: float = 0.0
    tier: str = TIER_NO_SIGNAL
    reason: str = ""


class SustainabilityPositioningOut(BaseModel):
    """Full sustainability-positioning read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    positioned: bool = False
    evidence_backed: bool = False
    claim_credibility: float = 0.0
    weighted_esg_affinity: float = 0.0
    weighted_conversion_lift: float = 0.0
    weighted_green_premium_tolerance: float = 0.0
    weighted_premium_friction: float = 0.0
    response_share: float = 0.0
    cluster_profiles: list[ClusterSustainabilityProfile] = Field(
        default_factory=list
    )
    top_opportunities: list[SustainabilityOpportunity] = Field(
        default_factory=list
    )
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterSustainabilityProfile",
    "SustainabilityOpportunity",
    "SustainabilityPositioningOut",
    "TIER_HIGH",
    "TIER_LOW",
    "TIER_MODERATE",
    "TIER_NO_SIGNAL",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_INSUFFICIENT",
    "VERDICT_MODERATE",
    "VERDICT_NOT_POSITIONED",
    "VERDICT_STRONG",
    "VERDICT_WEAK",
]
