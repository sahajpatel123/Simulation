"""
Pydantic schemas for the market-timing read
``GET /api/v1/simulations/{id}/market-timing``.

The endpoint answers the founder's "is now the right time to launch, and
where is readiness concentrated?" question from a completed run's
per-cluster ``MarketTimingArchitect`` metrics. It computes a
population-weighted timing index, tiers every covered cluster
``READY_NOW`` / ``ALMOST_READY`` / ``EARLY`` / ``BLOCKED``, attributes
each cluster's weakest readiness gate (regulation, category awareness,
problem urgency, category-education cost, switching cost, technology
adoption, budget cycle), and ranks the gates by the share of the
covered market they block.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_GO: str = "GO"
VERDICT_CAUTIOUS: str = "CAUTIOUS"
VERDICT_WAIT: str = "WAIT"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_GO,
        VERDICT_CAUTIOUS,
        VERDICT_WAIT,
        VERDICT_INSUFFICIENT,
    }
)

TIER_READY: str = "READY_NOW"
TIER_ALMOST: str = "ALMOST_READY"
TIER_EARLY: str = "EARLY"
TIER_BLOCKED: str = "BLOCKED"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_READY, TIER_ALMOST, TIER_EARLY, TIER_BLOCKED}
)

# Ordered readiness-gate keys. ``regulatory`` is first so a regulatory
# suppressor is never masked by a numerically equal awareness gap, and
# ``category_awareness`` is the fallback winner on ties so a generically
# unready read points at the education gap rather than a secondary gate.
GATE_REGULATORY: str = "regulatory"
GATE_AWARENESS: str = "category_awareness"
GATE_URGENCY: str = "problem_urgency"
GATE_EDUCATION: str = "category_education_cost"
GATE_SWITCHING: str = "switching_cost"
GATE_ADOPTION: str = "technology_adoption"
GATE_BUDGET: str = "budget_cycle"

VALID_GATES: frozenset[str] = frozenset(
    {
        GATE_REGULATORY,
        GATE_AWARENESS,
        GATE_URGENCY,
        GATE_EDUCATION,
        GATE_SWITCHING,
        GATE_ADOPTION,
        GATE_BUDGET,
    }
)


class ClusterTimingProfile(BaseModel):
    """One cluster's launch-readiness read from MarketTimingArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    category_awareness_score: float = 0.0
    problem_urgency_intensity: float = 0.0
    switching_cost_depth: float = 0.0
    budget_cycle_alignment: float = 0.0
    technology_adoption_score: float = 0.0
    trigger_event_sensitivity: float = 0.0
    category_creation_cost: float = 0.0
    seasonal_demand_coefficient: float = 1.0
    market_maturity_pricing_power: float = 0.0
    regulatory_dependency_risk: float = 0.0
    regulatory_suppressor: float = 1.0
    timing_index: float = 0.0
    readiness_tier: str = TIER_EARLY
    primary_gate: str = GATE_AWARENESS
    primary_gate_score: float = 0.0


class TopOpportunity(BaseModel):
    """One ready / nearly-ready cluster worth prioritizing at launch."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    timing_index: float = 0.0
    readiness_tier: str = TIER_EARLY
    primary_gate: str = GATE_AWARENESS


class MarketTimingOut(BaseModel):
    """Full market-timing read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    timing_index: float = 0.0
    weighted_category_awareness: float = 0.0
    weighted_problem_urgency: float = 0.0
    weighted_switching_cost: float = 0.0
    weighted_budget_cycle_alignment: float = 0.0
    weighted_technology_adoption: float = 0.0
    weighted_trigger_sensitivity: float = 0.0
    weighted_category_creation_cost: float = 0.0
    weighted_seasonal_coefficient: float = 1.0
    weighted_pricing_power: float = 0.0
    weighted_regulatory_risk: float = 0.0
    weighted_regulatory_suppressor: float = 1.0
    ready_share: float = 0.0
    almost_ready_share: float = 0.0
    early_share: float = 0.0
    blocked_share: float = 0.0
    primary_gate: str = GATE_AWARENESS
    primary_gate_label: str = "Category awareness"
    primary_gate_share: float = 0.0
    gate_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterTimingProfile] = Field(default_factory=list)
    top_opportunities: list[TopOpportunity] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterTimingProfile",
    "GATE_ADOPTION",
    "GATE_AWARENESS",
    "GATE_BUDGET",
    "GATE_EDUCATION",
    "GATE_REGULATORY",
    "GATE_SWITCHING",
    "GATE_URGENCY",
    "MarketTimingOut",
    "TIER_ALMOST",
    "TIER_BLOCKED",
    "TIER_EARLY",
    "TIER_READY",
    "TopOpportunity",
    "VALID_GATES",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_CAUTIOUS",
    "VERDICT_GO",
    "VERDICT_INSUFFICIENT",
    "VERDICT_WAIT",
]
