"""
Pydantic schemas for the setup-friction read
``GET /api/v1/simulations/{id}/setup-friction``.

The endpoint answers the founder's "how fast will buyers actually get
value from this hardware, and which setup step is blocking them?"
question from a completed run's per-cluster
``SetupFirstUseArchitect`` metrics. It computes a population-weighted
setup-experience index (0..1, higher = smoother / faster) from
out-of-box completion, time to first meaningful use, companion-app
install, account-creation abandonment, firmware-update tolerance,
physical-assembly tolerance and pairing tolerance, tiers every covered
cluster ``SEAMLESS`` / ``ROUGH`` / ``SLOW`` / ``BLOCKED``, attributes
each cluster's primary setup blocker, and ranks time-to-value levers by
the share of the covered market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_FAST: str = "FAST"
VERDICT_ACCEPTABLE: str = "ACCEPTABLE"
VERDICT_SLOW: str = "SLOW"
VERDICT_BLOCKED: str = "BLOCKED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_FAST,
        VERDICT_ACCEPTABLE,
        VERDICT_SLOW,
        VERDICT_BLOCKED,
        VERDICT_INSUFFICIENT,
    }
)

TIER_SEAMLESS: str = "SEAMLESS"
TIER_ROUGH: str = "ROUGH"
TIER_SLOW: str = "SLOW"
TIER_BLOCKED: str = "BLOCKED"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_SEAMLESS, TIER_ROUGH, TIER_SLOW, TIER_BLOCKED}
)

# Ordered setup-blocker keys. ``setup_completion`` is the fallback
# winner on ties so a generally-friction-heavy read points at raw
# out-of-box completion rather than a secondary setup step.
BLOCKER_SETUP_COMPLETION: str = "setup_completion"
BLOCKER_TIME_TO_VALUE: str = "time_to_value"
BLOCKER_COMPANION_APP: str = "companion_app"
BLOCKER_ACCOUNT_ABANDONMENT: str = "account_abandonment"
BLOCKER_FIRMWARE_UPDATE: str = "firmware_update"
BLOCKER_PHYSICAL_ASSEMBLY: str = "physical_assembly"
BLOCKER_PAIRING: str = "pairing"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_SETUP_COMPLETION,
        BLOCKER_TIME_TO_VALUE,
        BLOCKER_COMPANION_APP,
        BLOCKER_ACCOUNT_ABANDONMENT,
        BLOCKER_FIRMWARE_UPDATE,
        BLOCKER_PHYSICAL_ASSEMBLY,
        BLOCKER_PAIRING,
    }
)

LEVER_GUIDED_SETUP: str = "guided_setup"
LEVER_ONBOARDING_WIZARD: str = "onboarding_wizard"
LEVER_COMPANION_APP: str = "companion_app_setup"
LEVER_ACCOUNT_OPTIONAL: str = "account_optional"
LEVER_PREFLASHED_FIRMWARE: str = "preflashed_firmware"
LEVER_SIMPLIFIED_ASSEMBLY: str = "simplified_assembly"
LEVER_ONE_TAP_PAIRING: str = "one_tap_pairing"
LEVER_PRINTED_GUIDE: str = "printed_guide"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_GUIDED_SETUP,
        LEVER_ONBOARDING_WIZARD,
        LEVER_COMPANION_APP,
        LEVER_ACCOUNT_OPTIONAL,
        LEVER_PREFLASHED_FIRMWARE,
        LEVER_SIMPLIFIED_ASSEMBLY,
        LEVER_ONE_TAP_PAIRING,
        LEVER_PRINTED_GUIDE,
    }
)

# Product types whose conductor stack includes SetupFirstUseArchitect.
SUPPORTED_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
    }
)


class ClusterSetupProfile(BaseModel):
    """One cluster's setup-friction read from SetupFirstUseArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    oob_setup_completion_rate: float = 0.0
    companion_app_install_rate: float = 0.0
    account_creation_abandonment: float = 0.0
    firmware_update_tolerance_min: float = 0.0
    physical_assembly_tolerance: float = 0.0
    pairing_friction_tolerance: float = 0.0
    time_to_first_meaningful_use_min: float = 0.0
    initial_customisation_depth: float = 0.0
    setup_experience_index: float = 0.0
    setup_tier: str = TIER_SLOW
    primary_blocker: str = BLOCKER_SETUP_COMPLETION
    primary_blocker_score: float = 0.0
    architect_flags: list[str] = Field(default_factory=list)


class SetupLever(BaseModel):
    """One ranked setup / time-to-value lever and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class SetupFrictionOut(BaseModel):
    """Full setup-friction read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    setup_experience_index: float = 0.0
    weighted_oob_setup_completion_rate: float = 0.0
    weighted_companion_app_install_rate: float = 0.0
    weighted_account_creation_abandonment: float = 0.0
    weighted_time_to_first_meaningful_use_min: float = 0.0
    weighted_firmware_update_tolerance_min: float = 0.0
    weighted_physical_assembly_tolerance: float = 0.0
    weighted_pairing_friction_tolerance: float = 0.0
    seamless_share: float = 0.0
    rough_share: float = 0.0
    slow_share: float = 0.0
    blocked_share: float = 0.0
    primary_blocker: str = BLOCKER_SETUP_COMPLETION
    primary_blocker_label: str = "Low out-of-box setup completion"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterSetupProfile] = Field(
        default_factory=list
    )
    levers: list[SetupLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BLOCKER_ACCOUNT_ABANDONMENT",
    "BLOCKER_COMPANION_APP",
    "BLOCKER_FIRMWARE_UPDATE",
    "BLOCKER_PAIRING",
    "BLOCKER_PHYSICAL_ASSEMBLY",
    "BLOCKER_SETUP_COMPLETION",
    "BLOCKER_TIME_TO_VALUE",
    "ClusterSetupProfile",
    "LEVER_ACCOUNT_OPTIONAL",
    "LEVER_COMPANION_APP",
    "LEVER_GUIDED_SETUP",
    "LEVER_ONBOARDING_WIZARD",
    "LEVER_ONE_TAP_PAIRING",
    "LEVER_PREFLASHED_FIRMWARE",
    "LEVER_PRINTED_GUIDE",
    "LEVER_SIMPLIFIED_ASSEMBLY",
    "SetupFrictionOut",
    "SetupLever",
    "SUPPORTED_PRODUCT_TYPES",
    "TIER_BLOCKED",
    "TIER_ROUGH",
    "TIER_SEAMLESS",
    "TIER_SLOW",
    "VALID_BLOCKERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_ACCEPTABLE",
    "VERDICT_BLOCKED",
    "VERDICT_FAST",
    "VERDICT_INSUFFICIENT",
    "VERDICT_SLOW",
]
