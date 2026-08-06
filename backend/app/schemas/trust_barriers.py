"""
Pydantic schemas for the trust-barriers read
``GET /api/v1/simulations/{id}/trust-barriers``.

The endpoint answers the founder's "why won't they trust us, and what
removes the objection?" question from a completed run's per-cluster
``TrustArchitect`` metrics. It computes a population-weighted trust
index, tiers every covered cluster ``LOW`` / ``MODERATE`` / ``HIGH`` /
``CRITICAL``, attributes each cluster's primary trust barrier (brand
deficit, missing social proof, security concern, weak community
signals, trust decay, slow recovery), and ranks trust-building levers
by the share of the covered market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_LOW_BARRIER: str = "LOW_BARRIER"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_HIGH: str = "HIGH"
VERDICT_CRITICAL: str = "CRITICAL"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_LOW_BARRIER,
        VERDICT_MODERATE,
        VERDICT_HIGH,
        VERDICT_CRITICAL,
        VERDICT_INSUFFICIENT,
    }
)

TIER_LOW: str = "LOW"
TIER_MODERATE: str = "MODERATE"
TIER_HIGH: str = "HIGH"
TIER_CRITICAL: str = "CRITICAL"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_LOW, TIER_MODERATE, TIER_HIGH, TIER_CRITICAL}
)

# Ordered trust-barrier keys. ``brand_deficit`` is the fallback winner on
# ties so a generically untrusted read points at the brand-recognition gap
# rather than a secondary objection.
BARRIER_BRAND: str = "brand_deficit"
BARRIER_SOCIAL_PROOF: str = "social_proof"
BARRIER_SECURITY: str = "security_concern"
BARRIER_COMMUNITY: str = "community_signal"
BARRIER_DECAY: str = "trust_decay"
BARRIER_RECOVERY: str = "trust_recovery"

VALID_BARRIERS: frozenset[str] = frozenset(
    {
        BARRIER_BRAND,
        BARRIER_SOCIAL_PROOF,
        BARRIER_SECURITY,
        BARRIER_COMMUNITY,
        BARRIER_DECAY,
        BARRIER_RECOVERY,
    }
)

LEVER_SOCIAL_PROOF: str = "social_proof_building"
LEVER_FREE_TRIAL: str = "risk_free_trial"
LEVER_BRAND: str = "brand_credibility"
LEVER_SECURITY: str = "security_assurances"
LEVER_COMMUNITY: str = "community_signals"
LEVER_RECOVERY: str = "incident_response"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_SOCIAL_PROOF,
        LEVER_FREE_TRIAL,
        LEVER_BRAND,
        LEVER_SECURITY,
        LEVER_COMMUNITY,
        LEVER_RECOVERY,
    }
)


class ClusterTrustProfile(BaseModel):
    """One cluster's trust / objection read from TrustArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    brand_deficit_multiplier: float = 0.0
    social_proof_threshold: float = 0.0
    social_proof_met_fraction: float = 0.0
    security_concern_intensity: float = 0.0
    founder_vs_product_credibility: float = 0.0
    trust_decay_rate_per_incident: float = 0.0
    trust_recovery_days: float = 0.0
    community_size_signal_weight: float = 0.0
    press_mention_lift: float = 0.0
    free_trial_as_trust_substitute: float = 0.0
    trust_index: float = 0.0
    barrier_tier: str = TIER_MODERATE
    primary_barrier: str = BARRIER_BRAND
    primary_barrier_score: float = 0.0


class TrustLever(BaseModel):
    """One ranked trust-building intervention and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class TrustBarriersOut(BaseModel):
    """Full trust-barriers read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    trust_index: float = 0.0
    weighted_brand_deficit_multiplier: float = 0.0
    weighted_social_proof_met_fraction: float = 0.0
    weighted_security_concern_intensity: float = 0.0
    weighted_trust_decay_rate: float = 0.0
    weighted_trust_recovery_days: float = 0.0
    weighted_community_signal_weight: float = 0.0
    weighted_press_mention_lift: float = 0.0
    weighted_free_trial_substitute: float = 0.0
    low_share: float = 0.0
    moderate_share: float = 0.0
    high_share: float = 0.0
    critical_share: float = 0.0
    primary_barrier: str = BARRIER_BRAND
    primary_barrier_label: str = "Brand deficit"
    primary_barrier_share: float = 0.0
    barrier_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterTrustProfile] = Field(default_factory=list)
    levers: list[TrustLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BARRIER_BRAND",
    "BARRIER_COMMUNITY",
    "BARRIER_DECAY",
    "BARRIER_RECOVERY",
    "BARRIER_SECURITY",
    "BARRIER_SOCIAL_PROOF",
    "ClusterTrustProfile",
    "LEVER_BRAND",
    "LEVER_COMMUNITY",
    "LEVER_FREE_TRIAL",
    "LEVER_RECOVERY",
    "LEVER_SECURITY",
    "LEVER_SOCIAL_PROOF",
    "TIER_CRITICAL",
    "TIER_HIGH",
    "TIER_LOW",
    "TIER_MODERATE",
    "TrustBarriersOut",
    "TrustLever",
    "VALID_BARRIERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_CRITICAL",
    "VERDICT_HIGH",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LOW_BARRIER",
    "VERDICT_MODERATE",
]
