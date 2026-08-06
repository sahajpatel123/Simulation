"""
Pydantic schemas for the competitive-moat read
``GET /api/v1/simulations/{id}/competitive-moat``.

The endpoint answers the founder's "how defensible is this idea, and
where is it weakest?" question from a completed run's per-cluster
architect metrics. It combines the deterministic outputs of
``CompetitiveDynamicsArchitect``, ``TrustArchitect``,
``PricingArchitect`` and ``DistributionChannelArchitect`` into a
population-weighted moat index, per-cluster tiers
(``MOAT_STRONG`` / ``MOAT_MODERATE`` / ``MOAT_WEAK``), each cluster's
weakest defensibility lever, and the market-level lever that most
covered consumers are exposed on.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_STRONG: str = "STRONG"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_WEAK: str = "WEAK"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_STRONG,
        VERDICT_MODERATE,
        VERDICT_WEAK,
        VERDICT_INSUFFICIENT,
    }
)

TIER_STRONG: str = "MOAT_STRONG"
TIER_MODERATE: str = "MOAT_MODERATE"
TIER_WEAK: str = "MOAT_WEAK"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_STRONG, TIER_MODERATE, TIER_WEAK}
)

# Ordered moat-lever keys. The order is significant: ties for the
# weakest lever resolve to the earlier key so the read stays stable.
LEVER_FEATURE_PARITY: str = "feature_parity"
LEVER_BRAND_TRUST: str = "brand_trust"
LEVER_PRICING_POWER: str = "pricing_power"
LEVER_DISTRIBUTION: str = "distribution_reach"
LEVER_LOCK_IN: str = "switching_lock_in"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_FEATURE_PARITY,
        LEVER_BRAND_TRUST,
        LEVER_PRICING_POWER,
        LEVER_DISTRIBUTION,
        LEVER_LOCK_IN,
    }
)

LEVER_LABELS: dict[str, str] = {
    LEVER_FEATURE_PARITY: "Feature parity",
    LEVER_BRAND_TRUST: "Brand trust",
    LEVER_PRICING_POWER: "Pricing power",
    LEVER_DISTRIBUTION: "Distribution reach",
    LEVER_LOCK_IN: "Switching lock-in",
}


class ClusterMoatProfile(BaseModel):
    """One cluster's defensibility read from the architect stack."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    moat_index: float = 0.0
    moat_tier: str = TIER_WEAK
    levers: dict[str, float] = Field(default_factory=dict)
    weakest_lever: str = LEVER_FEATURE_PARITY
    displacement_days: int = 45
    flags: list[str] = Field(default_factory=list)


class MoatOpportunity(BaseModel):
    """One protected / vulnerable cluster worth acting on."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    moat_index: float = 0.0
    moat_tier: str = TIER_WEAK
    weakest_lever: str = LEVER_FEATURE_PARITY


class CompetitiveMoatOut(BaseModel):
    """Full competitive-moat read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    moat_index: float = 0.0
    weighted_feature_parity: float = 0.0
    weighted_brand_trust: float = 0.0
    weighted_pricing_power: float = 0.0
    weighted_distribution_reach: float = 0.0
    weighted_switching_lock_in: float = 0.0
    strong_share: float = 0.0
    moderate_share: float = 0.0
    weak_share: float = 0.0
    primary_weakest_lever: str = LEVER_FEATURE_PARITY
    primary_weakest_lever_label: str = "Feature parity"
    primary_weakest_lever_share: float = 0.0
    lever_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterMoatProfile] = Field(default_factory=list)
    top_protected: list[MoatOpportunity] = Field(default_factory=list)
    top_vulnerable: list[MoatOpportunity] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterMoatProfile",
    "CompetitiveMoatOut",
    "LEVER_BRAND_TRUST",
    "LEVER_DISTRIBUTION",
    "LEVER_FEATURE_PARITY",
    "LEVER_LABELS",
    "LEVER_LOCK_IN",
    "LEVER_PRICING_POWER",
    "MoatOpportunity",
    "TIER_MODERATE",
    "TIER_STRONG",
    "TIER_WEAK",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_INSUFFICIENT",
    "VERDICT_MODERATE",
    "VERDICT_STRONG",
    "VERDICT_WEAK",
]
