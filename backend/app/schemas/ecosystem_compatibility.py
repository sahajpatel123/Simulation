"""
Pydantic schemas for the ecosystem-compatibility read
``GET /api/v1/simulations/{id}/ecosystem-compatibility``.

The endpoint answers the founder's "is my hardware too dependent on
someone else's ecosystem, and which compatibility lever should I pull
first?" question from a completed run's per-cluster
``EcosystemCompatibilityArchitect`` metrics. It computes a
population-weighted compatibility index (0..1, higher = more open /
compatible), tiers every covered cluster ``OPEN`` / ``PARTIAL`` /
``TETHERED`` / ``LOCKED``, attributes each cluster's primary
compatibility blocker (platform lock-in, smart-home gate, subscription
resentment, cloud privacy, voice expectation), and ranks ecosystem
levers by the share of the covered market they touch.
``EcosystemCompatibilityArchitect`` activates for consumer_hardware,
health_hardware, iot_hardware, smart_home and wearable product types.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_SEAMLESS: str = "SEAMLESS"
VERDICT_WORKABLE: str = "WORKABLE"
VERDICT_FRAGILE: str = "FRAGILE"
VERDICT_BLOCKED: str = "BLOCKED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_SEAMLESS,
        VERDICT_WORKABLE,
        VERDICT_FRAGILE,
        VERDICT_BLOCKED,
        VERDICT_INSUFFICIENT,
    }
)

TIER_OPEN: str = "OPEN"
TIER_PARTIAL: str = "PARTIAL"
TIER_TETHERED: str = "TETHERED"
TIER_LOCKED: str = "LOCKED"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_OPEN, TIER_PARTIAL, TIER_TETHERED, TIER_LOCKED}
)

# Ordered compatibility-blocker keys. ``platform_lockin`` is the
# fallback winner on ties so a generally-weak read points at the most
# common, most actionable blocker (openness) rather than a secondary
# integration gap.
BLOCKER_LOCKIN: str = "platform_lockin"
BLOCKER_SMART_HOME: str = "smart_home_gate"
BLOCKER_SUBSCRIPTION: str = "subscription_resentment"
BLOCKER_CLOUD: str = "cloud_privacy"
BLOCKER_VOICE: str = "voice_expectation"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_LOCKIN,
        BLOCKER_SMART_HOME,
        BLOCKER_SUBSCRIPTION,
        BLOCKER_CLOUD,
        BLOCKER_VOICE,
    }
)

LEVER_MATTER: str = "matter_smart_home_support"
LEVER_API: str = "open_api_sdk"
LEVER_SUBSCRIPTION: str = "optional_subscription"
LEVER_PRIVACY: str = "local_private_mode"
LEVER_VOICE: str = "voice_assistant_integration"
LEVER_HOUSEHOLD: str = "household_multi_user_design"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_MATTER,
        LEVER_API,
        LEVER_SUBSCRIPTION,
        LEVER_PRIVACY,
        LEVER_VOICE,
        LEVER_HOUSEHOLD,
    }
)


class ClusterEcosystemProfile(BaseModel):
    """One cluster's ecosystem-compatibility read from
    EcosystemCompatibilityArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    platform_lockin_acceptance: float = 0.0
    smart_home_compatibility_requirement: float = 0.0
    subscription_hardware_resentment: float = 0.0
    cloud_storage_tolerance: float = 0.0
    developer_api_interest: float = 0.0
    cross_device_interoperability: float = 0.0
    household_sharing_behaviour: float = 0.0
    voice_assistant_expectation: float = 0.0
    ecosystem_compatibility_gate: float = 0.0
    compatibility_index: float = 0.0
    compatibility_tier: str = TIER_LOCKED
    primary_blocker: str = BLOCKER_LOCKIN
    primary_blocker_score: float = 0.0
    architect_flags: list[str] = Field(default_factory=list)


class EcosystemLever(BaseModel):
    """One ranked ecosystem lever and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class EcosystemCompatibilityOut(BaseModel):
    """Full ecosystem-compatibility read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    compatibility_index: float = 0.0
    weighted_platform_lockin_acceptance: float = 0.0
    weighted_smart_home_requirement: float = 0.0
    weighted_subscription_resentment: float = 0.0
    weighted_cloud_tolerance: float = 0.0
    weighted_developer_api_interest: float = 0.0
    weighted_cross_device_interoperability: float = 0.0
    weighted_household_sharing: float = 0.0
    weighted_voice_expectation: float = 0.0
    weighted_compatibility_gate: float = 0.0
    open_share: float = 0.0
    partial_share: float = 0.0
    tethered_share: float = 0.0
    locked_share: float = 0.0
    primary_blocker: str = BLOCKER_LOCKIN
    primary_blocker_label: str = "Platform lock-in resistance"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterEcosystemProfile] = Field(
        default_factory=list
    )
    levers: list[EcosystemLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BLOCKER_CLOUD",
    "BLOCKER_LOCKIN",
    "BLOCKER_SMART_HOME",
    "BLOCKER_SUBSCRIPTION",
    "BLOCKER_VOICE",
    "ClusterEcosystemProfile",
    "EcosystemCompatibilityOut",
    "EcosystemLever",
    "LEVER_API",
    "LEVER_HOUSEHOLD",
    "LEVER_MATTER",
    "LEVER_PRIVACY",
    "LEVER_SUBSCRIPTION",
    "LEVER_VOICE",
    "TIER_LOCKED",
    "TIER_OPEN",
    "TIER_PARTIAL",
    "TIER_TETHERED",
    "VALID_BLOCKERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_BLOCKED",
    "VERDICT_FRAGILE",
    "VERDICT_INSUFFICIENT",
    "VERDICT_SEAMLESS",
    "VERDICT_WORKABLE",
]
