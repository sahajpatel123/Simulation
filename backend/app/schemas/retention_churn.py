"""
Pydantic schemas for the retention-churn read
``GET /api/v1/simulations/{id}/retention-churn``.

The endpoint answers the founder's "will users stick around, and which
retention lever should I pull first?" question from a completed run's
per-cluster ``RetentionArchitect`` metrics. It computes a
population-weighted survival curve (day 1 / 7 / 30 / 90), tiers every
covered cluster ``STICKY`` / ``STEADY`` / ``FADING`` / ``HIGH_CHURN``,
attributes each cluster's primary churn trigger (price, onboarding,
feature depth, habit loop), identifies the market's biggest survival
drop-off stage, and ranks retention levers by the share of the covered
market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_STRONG: str = "STRONG"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_WEAK: str = "WEAK"
VERDICT_CRITICAL: str = "CRITICAL"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_STRONG,
        VERDICT_MODERATE,
        VERDICT_WEAK,
        VERDICT_CRITICAL,
        VERDICT_INSUFFICIENT,
    }
)

TIER_STICKY: str = "STICKY"
TIER_STEADY: str = "STEADY"
TIER_FADING: str = "FADING"
TIER_HIGH_CHURN: str = "HIGH_CHURN"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_STICKY, TIER_STEADY, TIER_FADING, TIER_HIGH_CHURN}
)

# Ordered churn-trigger keys. ``price`` is the fallback winner on ties so
# a generically weak retention read points at affordability before the
# secondary domains.
TRIGGER_PRICE: str = "price"
TRIGGER_ONBOARDING: str = "onboarding"
TRIGGER_HABIT: str = "habit"
TRIGGER_FEATURE: str = "feature"

VALID_TRIGGERS: frozenset[str] = frozenset(
    {TRIGGER_PRICE, TRIGGER_ONBOARDING, TRIGGER_HABIT, TRIGGER_FEATURE}
)

LEVER_ONBOARDING: str = "onboarding_improvement"
LEVER_HABIT: str = "habit_loop_design"
LEVER_FEATURE: str = "feature_depth"
LEVER_PRICING: str = "pricing_flexibility"
LEVER_SUPPORT: str = "support_reduction"
LEVER_WINBACK: str = "winback_engagement"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_ONBOARDING,
        LEVER_HABIT,
        LEVER_FEATURE,
        LEVER_PRICING,
        LEVER_SUPPORT,
        LEVER_WINBACK,
    }
)

# Survival drop-off stages, oldest first (used for tie-breaking so an
# earlier cliff wins when drops are equal).
STAGE_DAY1: str = "day1"
STAGE_DAY7: str = "day7"
STAGE_DAY30: str = "day30"
STAGE_DAY90: str = "day90"

VALID_STAGES: frozenset[str] = frozenset(
    {STAGE_DAY1, STAGE_DAY7, STAGE_DAY30, STAGE_DAY90}
)


class ClusterRetentionProfile(BaseModel):
    """One cluster's survival / churn read from RetentionArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    day1_survival: float = 0.0
    day7_survival: float = 0.0
    day30_survival: float = 0.0
    day90_survival: float = 0.0
    habit_loop_formation_days: float = 0.0
    reengagement_probability_30d: float = 0.0
    notification_reengagement_rate: float = 0.0
    pause_vs_cancel_preference: float = 0.0
    session_pattern: str = "quick_check"
    onboarding_completion_rate: float = 0.0
    feature_depth_score: float = 0.0
    will_pay_probability: float = 0.0
    support_ticket_likelihood: float = 0.0
    retention_tier: str = TIER_HIGH_CHURN
    primary_churn_trigger: str = TRIGGER_PRICE
    primary_churn_trigger_score: float = 0.0


class RetentionLever(BaseModel):
    """One ranked retention intervention and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class RetentionChurnOut(BaseModel):
    """Full retention-churn read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    weighted_day1_survival: float = 0.0
    weighted_day7_survival: float = 0.0
    weighted_day30_survival: float = 0.0
    weighted_day90_survival: float = 0.0
    weighted_habit_loop_days: float = 0.0
    weighted_reengagement_30d: float = 0.0
    weighted_notification_reengagement: float = 0.0
    weighted_pause_vs_cancel: float = 0.0
    deep_work_share: float = 0.0
    highest_churn_stage: str = STAGE_DAY1
    sticky_share: float = 0.0
    steady_share: float = 0.0
    fading_share: float = 0.0
    high_churn_share: float = 0.0
    primary_churn_trigger: str = TRIGGER_PRICE
    primary_churn_trigger_label: str = "Price sensitivity"
    primary_churn_trigger_share: float = 0.0
    churn_trigger_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterRetentionProfile] = Field(default_factory=list)
    levers: list[RetentionLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterRetentionProfile",
    "LEVER_FEATURE",
    "LEVER_HABIT",
    "LEVER_ONBOARDING",
    "LEVER_PRICING",
    "LEVER_SUPPORT",
    "LEVER_WINBACK",
    "RetentionChurnOut",
    "RetentionLever",
    "STAGE_DAY1",
    "STAGE_DAY30",
    "STAGE_DAY7",
    "STAGE_DAY90",
    "TIER_FADING",
    "TIER_HIGH_CHURN",
    "TIER_STEADY",
    "TIER_STICKY",
    "TRIGGER_FEATURE",
    "TRIGGER_HABIT",
    "TRIGGER_ONBOARDING",
    "TRIGGER_PRICE",
    "VALID_LEVERS",
    "VALID_STAGES",
    "VALID_TIERS",
    "VALID_TRIGGERS",
    "VALID_VERDICTS",
    "VERDICT_CRITICAL",
    "VERDICT_INSUFFICIENT",
    "VERDICT_MODERATE",
    "VERDICT_STRONG",
    "VERDICT_WEAK",
]
