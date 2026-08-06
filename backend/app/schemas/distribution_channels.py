"""
Pydantic schemas for the distribution-channels read
``GET /api/v1/simulations/{id}/distribution-channels``.

The endpoint answers the hardware founder's "can my market actually buy
this product, and which channel lever moves demand first?" question
from a completed run's per-cluster ``DistributionChannelArchitect``
metrics. It computes a population-weighted channel-readiness read
(accessibility, online preference, try-before-buy, influencer
dependency, cashback sensitivity, delivery speed, and platform
preferences), classifies every covered cluster
``OMNICHANNEL`` / ``ONLINE`` / ``LIMITED_ACCESS`` / ``ACCESS_GAP``,
attributes each cluster's primary distribution blocker (access,
try-before-buy, influencer verification, cashback/loyalty, delivery
speed, platform presence), and ranks distribution levers by the share
of the covered market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_OMNICHANNEL: str = "OMNICHANNEL"
VERDICT_ONLINE_FIRST: str = "ONLINE_FIRST"
VERDICT_ACCESS_GAP: str = "ACCESS_GAP"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_OMNICHANNEL,
        VERDICT_ONLINE_FIRST,
        VERDICT_ACCESS_GAP,
        VERDICT_INSUFFICIENT,
    }
)

TIER_OMNICHANNEL: str = "OMNICHANNEL"
TIER_ONLINE: str = "ONLINE"
TIER_LIMITED_ACCESS: str = "LIMITED_ACCESS"
TIER_ACCESS_GAP: str = "ACCESS_GAP"

VALID_TIERS: frozenset[str] = frozenset(
    {
        TIER_OMNICHANNEL,
        TIER_ONLINE,
        TIER_LIMITED_ACCESS,
        TIER_ACCESS_GAP,
    }
)

# Ordered distribution-blocker keys. ``distribution_access`` is the
# fallback winner on ties so a generically weak channel read points at
# physical availability rather than a secondary channel.
BLOCKER_ACCESS: str = "distribution_access"
BLOCKER_TRY_BEFORE_BUY: str = "try_before_buy"
BLOCKER_INFLUENCER: str = "influencer_verification"
BLOCKER_CASHBACK: str = "cashback_loyalty"
BLOCKER_DELIVERY: str = "delivery_speed"
BLOCKER_PLATFORM: str = "platform_presence"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_ACCESS,
        BLOCKER_TRY_BEFORE_BUY,
        BLOCKER_INFLUENCER,
        BLOCKER_CASHBACK,
        BLOCKER_DELIVERY,
        BLOCKER_PLATFORM,
    }
)

LEVER_OFFLINE: str = "offline_distribution"
LEVER_TRY_BEFORE_BUY: str = "try_before_buy_program"
LEVER_INFLUENCER: str = "influencer_program"
LEVER_CASHBACK: str = "cashback_loyalty_program"
LEVER_DELIVERY: str = "delivery_speed"
LEVER_PLATFORM: str = "platform_expansion"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_OFFLINE,
        LEVER_TRY_BEFORE_BUY,
        LEVER_INFLUENCER,
        LEVER_CASHBACK,
        LEVER_DELIVERY,
        LEVER_PLATFORM,
    }
)


class ClusterChannelProfile(BaseModel):
    """One cluster's distribution-channel readiness read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    online_preference: float = 0.0
    distribution_accessibility_multiplier: float = 0.0
    delivery_speed_days_required: float = 0.0
    try_before_buy_requirement: float = 0.0
    influencer_review_dependency: float = 0.0
    cashback_loyalty_sensitivity: float = 0.0
    platform_pref_amazon: float = 0.0
    platform_pref_flipkart: float = 0.0
    platform_pref_brand_direct: float = 0.0
    platform_pref_offline: float = 0.0
    channel_tier: str = TIER_ACCESS_GAP
    primary_blocker: str = BLOCKER_ACCESS
    primary_blocker_score: float = 0.0


class DistributionLever(BaseModel):
    """One ranked distribution intervention and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class DistributionChannelsOut(BaseModel):
    """Full distribution-channels read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "consumer_hardware"
    verdict: str = VERDICT_INSUFFICIENT
    weighted_online_preference: float = 0.0
    weighted_accessibility: float = 0.0
    weighted_try_before_buy: float = 0.0
    weighted_influencer_dependency: float = 0.0
    weighted_cashback_sensitivity: float = 0.0
    weighted_delivery_days: float = 0.0
    weighted_platform_amazon: float = 0.0
    weighted_platform_flipkart: float = 0.0
    weighted_platform_brand_direct: float = 0.0
    weighted_platform_offline: float = 0.0
    omnichannel_share: float = 0.0
    online_share: float = 0.0
    limited_access_share: float = 0.0
    access_gap_share: float = 0.0
    primary_blocker: str = BLOCKER_ACCESS
    primary_blocker_label: str = "Distribution access"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterChannelProfile] = Field(default_factory=list)
    levers: list[DistributionLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BLOCKER_ACCESS",
    "BLOCKER_CASHBACK",
    "BLOCKER_DELIVERY",
    "BLOCKER_INFLUENCER",
    "BLOCKER_PLATFORM",
    "BLOCKER_TRY_BEFORE_BUY",
    "ClusterChannelProfile",
    "DistributionChannelsOut",
    "DistributionLever",
    "LEVER_CASHBACK",
    "LEVER_DELIVERY",
    "LEVER_INFLUENCER",
    "LEVER_OFFLINE",
    "LEVER_PLATFORM",
    "LEVER_TRY_BEFORE_BUY",
    "TIER_ACCESS_GAP",
    "TIER_LIMITED_ACCESS",
    "TIER_OMNICHANNEL",
    "TIER_ONLINE",
    "VALID_BLOCKERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_ACCESS_GAP",
    "VERDICT_INSUFFICIENT",
    "VERDICT_OMNICHANNEL",
    "VERDICT_ONLINE_FIRST",
]
