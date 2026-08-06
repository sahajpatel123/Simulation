"""
Pydantic schemas for the virality-growth read
``GET /api/v1/simulations/{id}/virality-growth``.

The endpoint answers the founder's "will this product spread by word of
mouth, and which growth levers move the market?" question from a
completed run's per-cluster ``ViralityArchitect`` metrics. It computes a
population-weighted viral coefficient (K), classifies every covered
cluster ``VIRAL`` / ``PROMISING`` / ``EMERGING`` / ``WEAK``, attributes
each cluster's primary growth blocker (organic trigger, invite
completion, incentive quality, word of mouth, content virality,
community), and ranks growth levers by the share of the covered market
they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_VIRAL: str = "VIRAL"
VERDICT_MOMENTUM: str = "MOMENTUM"
VERDICT_LIMITED: str = "LIMITED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_VIRAL, VERDICT_MOMENTUM, VERDICT_LIMITED, VERDICT_INSUFFICIENT}
)

TIER_VIRAL: str = "VIRAL"
TIER_PROMISING: str = "PROMISING"
TIER_EMERGING: str = "EMERGING"
TIER_WEAK: str = "WEAK"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_VIRAL, TIER_PROMISING, TIER_EMERGING, TIER_WEAK}
)

# Ordered growth-blocker keys. ``organic_trigger`` is the fallback winner
# on ties so a generically weak growth read points at the top-of-funnel
# sharing moment rather than a secondary channel.
BLOCKER_TRIGGER: str = "organic_trigger"
BLOCKER_INVITE: str = "invite_completion"
BLOCKER_INCENTIVE: str = "incentive_quality"
BLOCKER_WOM: str = "word_of_mouth"
BLOCKER_CONTENT: str = "content_virality"
BLOCKER_COMMUNITY: str = "community"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_TRIGGER,
        BLOCKER_INVITE,
        BLOCKER_INCENTIVE,
        BLOCKER_WOM,
        BLOCKER_CONTENT,
        BLOCKER_COMMUNITY,
    }
)

LEVER_REFERRAL: str = "referral_program"
LEVER_INCENTIVES: str = "incentive_design"
LEVER_SHAREABLE: str = "shareable_output"
LEVER_COMMUNITY: str = "community_building"
LEVER_WOM: str = "wom_channels"
LEVER_ORGANIC: str = "organic_triggers"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_REFERRAL,
        LEVER_INCENTIVES,
        LEVER_SHAREABLE,
        LEVER_COMMUNITY,
        LEVER_WOM,
        LEVER_ORGANIC,
    }
)


class ClusterGrowthProfile(BaseModel):
    """One cluster's word-of-mouth / viral-growth read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    viral_coefficient: float = 0.0
    organic_referral_trigger_score: float = 0.0
    referral_incentive_response_quality: float = 0.0
    word_of_mouth_coefficient: float = 0.0
    network_effect_threshold: float = 0.0
    invite_completion_rate: float = 0.0
    content_virality_rate: float = 0.0
    community_building_participation: float = 0.0
    growth_tier: str = TIER_WEAK
    primary_blocker: str = BLOCKER_TRIGGER
    primary_blocker_score: float = 0.0


class GrowthLever(BaseModel):
    """One ranked growth intervention and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class ViralityGrowthOut(BaseModel):
    """Full virality-growth read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    weighted_viral_coefficient: float = 0.0
    weighted_organic_trigger: float = 0.0
    weighted_invite_completion: float = 0.0
    weighted_incentive_quality: float = 0.0
    weighted_wom_coefficient: float = 0.0
    weighted_content_virality: float = 0.0
    weighted_community_participation: float = 0.0
    weighted_network_effect_threshold: float = 0.0
    viral_share: float = 0.0
    momentum_share: float = 0.0
    primary_blocker: str = BLOCKER_TRIGGER
    primary_blocker_label: str = "Organic sharing trigger"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterGrowthProfile] = Field(default_factory=list)
    levers: list[GrowthLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BLOCKER_COMMUNITY",
    "BLOCKER_CONTENT",
    "BLOCKER_INCENTIVE",
    "BLOCKER_INVITE",
    "BLOCKER_TRIGGER",
    "BLOCKER_WOM",
    "ClusterGrowthProfile",
    "GrowthLever",
    "LEVER_COMMUNITY",
    "LEVER_INCENTIVES",
    "LEVER_ORGANIC",
    "LEVER_REFERRAL",
    "LEVER_SHAREABLE",
    "LEVER_WOM",
    "TIER_EMERGING",
    "TIER_PROMISING",
    "TIER_VIRAL",
    "TIER_WEAK",
    "VALID_BLOCKERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LIMITED",
    "VERDICT_MOMENTUM",
    "VERDICT_VIRAL",
    "ViralityGrowthOut",
]
