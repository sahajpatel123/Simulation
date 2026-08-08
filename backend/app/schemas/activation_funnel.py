"""
Pydantic schemas for the activation-funnel read
``GET /api/v1/simulations/{id}/activation-funnel``.

The endpoint answers the founder's "why do first-time users drop before
first value, and what should I fix?" question from a completed run's
per-cluster ``OnboardingArchitect`` metrics. It computes a
population-weighted activation rate, tiers every cluster
``STRONG`` / ``MODERATE`` / ``WEAK`` / ``CRITICAL``, attributes each
cluster's primary activation blocker, and ranks activation levers by the
share of the covered market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_READY: str = "READY"
VERDICT_AT_RISK: str = "AT_RISK"
VERDICT_BLOCKED: str = "BLOCKED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_READY, VERDICT_AT_RISK, VERDICT_BLOCKED, VERDICT_INSUFFICIENT}
)

TIER_STRONG: str = "STRONG"
TIER_MODERATE: str = "MODERATE"
TIER_WEAK: str = "WEAK"
TIER_CRITICAL: str = "CRITICAL"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_STRONG, TIER_MODERATE, TIER_WEAK, TIER_CRITICAL}
)

# Ordered activation-blocker keys. ``completion`` is the fallback winner
# on ties so a generically weak first run reads as an onboarding-completion
# problem rather than a secondary friction point.
BLOCKER_COMPLETION: str = "completion"
BLOCKER_EMPTY_STATE: str = "empty_state"
BLOCKER_IDENTITY: str = "identity_friction"
BLOCKER_MANDATORY_PROFILE: str = "mandatory_profile"
BLOCKER_MOBILE_GAP: str = "mobile_gap"
BLOCKER_PERMISSION_TIMING: str = "permission_timing"
BLOCKER_TIME_TO_VALUE: str = "time_to_value"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_COMPLETION,
        BLOCKER_EMPTY_STATE,
        BLOCKER_IDENTITY,
        BLOCKER_MANDATORY_PROFILE,
        BLOCKER_MOBILE_GAP,
        BLOCKER_PERMISSION_TIMING,
        BLOCKER_TIME_TO_VALUE,
    }
)

LEVER_SIMPLIFY: str = "simplify_onboarding"
LEVER_TEMPLATES: str = "templates_first_run"
LEVER_SOCIAL_PROOF: str = "social_proof"
LEVER_PERMISSION_TIMING: str = "permission_timing"
LEVER_MOBILE: str = "mobile_experience"
LEVER_IDENTITY: str = "identity_reduction"
LEVER_DISCLOSURE: str = "progressive_disclosure"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_SIMPLIFY,
        LEVER_TEMPLATES,
        LEVER_SOCIAL_PROOF,
        LEVER_PERMISSION_TIMING,
        LEVER_MOBILE,
        LEVER_IDENTITY,
        LEVER_DISCLOSURE,
    }
)


class ClusterActivationProfile(BaseModel):
    """One cluster's first-run activation read from OnboardingArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    onboarding_completion_rate: float = 0.0
    time_to_first_value_tolerance: float = 0.0
    empty_state_bounce_probability: float = 0.0
    progressive_disclosure_limit: float = 0.0
    mobile_completion_penalty: float = 0.0
    permission_timing_sensitivity: float = 0.0
    mandatory_profile_churn_risk: float = 0.0
    video_walkthrough_skip_rate: float = 0.0
    social_onboarding_lift: float = 0.0
    template_vs_blank_preference: float = 0.0
    identity_verification_friction: float = 0.0
    activation_tier: str = TIER_WEAK
    primary_blocker: str = BLOCKER_COMPLETION
    primary_blocker_score: float = 0.0


class ActivationLever(BaseModel):
    """One ranked activation intervention and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class ActivationFunnelOut(BaseModel):
    """Full activation-funnel read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    activation_rate: float = 0.0
    time_to_first_value_minutes: float = 0.0
    empty_state_bounce_probability: float = 0.0
    progressive_disclosure_limit: float = 0.0
    mobile_gap_share: float = 0.0
    identity_friction_weighted: float = 0.0
    mandatory_profile_churn_weighted: float = 0.0
    permission_timing_weighted: float = 0.0
    social_onboarding_lift_weighted: float = 0.0
    template_preference_weighted: float = 0.0
    primary_blocker: str = BLOCKER_COMPLETION
    primary_blocker_label: str = "Onboarding completion"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterActivationProfile] = Field(default_factory=list)
    levers: list[ActivationLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ActivationFunnelOut",
    "ActivationLever",
    "BLOCKER_COMPLETION",
    "BLOCKER_EMPTY_STATE",
    "BLOCKER_IDENTITY",
    "BLOCKER_MANDATORY_PROFILE",
    "BLOCKER_MOBILE_GAP",
    "BLOCKER_PERMISSION_TIMING",
    "BLOCKER_TIME_TO_VALUE",
    "ClusterActivationProfile",
    "LEVER_DISCLOSURE",
    "LEVER_IDENTITY",
    "LEVER_MOBILE",
    "LEVER_PERMISSION_TIMING",
    "LEVER_SIMPLIFY",
    "LEVER_SOCIAL_PROOF",
    "LEVER_TEMPLATES",
    "TIER_CRITICAL",
    "TIER_MODERATE",
    "TIER_STRONG",
    "TIER_WEAK",
    "VALID_BLOCKERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_AT_RISK",
    "VERDICT_BLOCKED",
    "VERDICT_INSUFFICIENT",
    "VERDICT_READY",
]
