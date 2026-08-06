"""
Pydantic schemas for the support-friction read
``GET /api/v1/simulations/{id}/support-friction``.

The endpoint answers the founder's "how much support burden will this
customer base create, and which levers remove it?" question from a
completed run's per-cluster ``SupportFrictionArchitect`` metrics. It
computes a population-weighted friction index (0..1, higher = worse)
from ticket likelihood, self-serve resolution, response-time tolerance,
bug tolerance, downtime sensitivity, and documentation perception,
tiers every covered cluster ``LOW`` / ``MODERATE`` / ``HIGH`` /
``CRITICAL``, attributes each cluster's primary friction driver, and
ranks support-reduction levers by the share of the covered market they
touch. It also estimates monthly support contacts and the equivalent
staffing per 10k users so the burden is tangible.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_LOW_BURDEN: str = "LOW_BURDEN"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_HIGH: str = "HIGH"
VERDICT_CRITICAL: str = "CRITICAL"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_LOW_BURDEN,
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

# Ordered friction-driver keys. ``ticket_volume`` is the fallback winner
# on ties so a generally-friction-heavy read points at raw ticket load
# rather than a secondary driver.
DRIVER_TICKET: str = "ticket_volume"
DRIVER_SELF_SERVE: str = "self_serve_gap"
DRIVER_RESPONSE: str = "response_tolerance"
DRIVER_BUG: str = "bug_tolerance"
DRIVER_DOWNTIME: str = "downtime_sensitivity"
DRIVER_DOCS: str = "documentation_gap"

VALID_DRIVERS: frozenset[str] = frozenset(
    {
        DRIVER_TICKET,
        DRIVER_SELF_SERVE,
        DRIVER_RESPONSE,
        DRIVER_BUG,
        DRIVER_DOWNTIME,
        DRIVER_DOCS,
    }
)

LEVER_DOCS: str = "documentation_and_onboarding"
LEVER_SELF_SERVE: str = "self_service_build"
LEVER_CHAT: str = "live_chat"
LEVER_ONBOARDING: str = "ticket_prevention"
LEVER_RELIABILITY: str = "reliability_sla"
LEVER_QUALITY: str = "quality_gate"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_DOCS,
        LEVER_SELF_SERVE,
        LEVER_CHAT,
        LEVER_ONBOARDING,
        LEVER_RELIABILITY,
        LEVER_QUALITY,
    }
)


class ClusterFrictionProfile(BaseModel):
    """One cluster's support-friction read from SupportFrictionArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    support_ticket_likelihood: float = 0.0
    self_serve_resolution_rate: float = 0.0
    response_time_tolerance_hours: float = 0.0
    bug_tolerance_threshold: float = 0.0
    downtime_sensitivity: float = 0.0
    documentation_quality_perception_effect: float = 0.0
    friction_index: float = 0.0
    friction_tier: str = TIER_MODERATE
    primary_driver: str = DRIVER_TICKET
    primary_driver_score: float = 0.0
    architect_flags: list[str] = Field(default_factory=list)


class SupportLever(BaseModel):
    """One ranked support-reduction lever and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class SupportFrictionOut(BaseModel):
    """Full support-friction read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    friction_index: float = 0.0
    weighted_ticket_likelihood: float = 0.0
    weighted_self_serve_resolution_rate: float = 0.0
    weighted_response_time_tolerance_hours: float = 0.0
    weighted_bug_tolerance_threshold: float = 0.0
    weighted_downtime_sensitivity: float = 0.0
    weighted_documentation_effect: float = 0.0
    estimated_monthly_contacts_per_10k_users: int = 0
    estimated_support_agents_per_10k_users: float = 0.0
    low_share: float = 0.0
    moderate_share: float = 0.0
    high_share: float = 0.0
    critical_share: float = 0.0
    primary_driver: str = DRIVER_TICKET
    primary_driver_label: str = "Ticket volume"
    primary_driver_share: float = 0.0
    driver_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterFrictionProfile] = Field(
        default_factory=list
    )
    levers: list[SupportLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterFrictionProfile",
    "DRIVER_BUG",
    "DRIVER_DOCS",
    "DRIVER_DOWNTIME",
    "DRIVER_RESPONSE",
    "DRIVER_SELF_SERVE",
    "DRIVER_TICKET",
    "LEVER_CHAT",
    "LEVER_DOCS",
    "LEVER_ONBOARDING",
    "LEVER_QUALITY",
    "LEVER_RELIABILITY",
    "LEVER_SELF_SERVE",
    "SupportFrictionOut",
    "SupportLever",
    "TIER_CRITICAL",
    "TIER_HIGH",
    "TIER_LOW",
    "TIER_MODERATE",
    "VALID_DRIVERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_CRITICAL",
    "VERDICT_HIGH",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LOW_BURDEN",
    "VERDICT_MODERATE",
]
