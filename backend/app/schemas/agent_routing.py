"""
Pydantic schemas for the agent-hierarchy routing endpoints.

The ``AgentHierarchyRouter`` in ``app/simulation/agent_hierarchy.py`` chooses
between MICRO (fast stochastic), WORKER (full browser), and SUPERVISOR
(deliberating) tiers for each consumer cluster when running UI simulations.
These schemas expose the routing decisions to API consumers without leaking
the raw dataclass.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AgentTierEnum(str, Enum):
    """Public mirror of ``app.simulation.agent_hierarchy.AgentTier``."""

    MICRO = "MICRO"
    WORKER = "WORKER"
    SUPERVISOR = "SUPERVISOR"


# Relative cost for running one agent at a tier. These are *qualitative*
# multipliers, surfaced so users can predict runtime / token spend without
# reading the simulation engine. Real per-tier costs vary by product type.
TIER_RELATIVE_COST: dict[str, float] = {
    "MICRO": 0.05,
    "WORKER": 1.0,
    "SUPERVISOR": 3.5,
}


def _tier_cost(tier: AgentTierEnum) -> float:
    return TIER_RELATIVE_COST.get(tier.value, 1.0)


class AgentRoutingDecisionOut(BaseModel):
    """One cluster's routing decision."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cluster_id": "senior_enterprise_decision_maker",
                "tier": "SUPERVISOR",
                "reason": "Enterprise/health/complex deliberation cluster",
                "confidence": 0.95,
                "needs_browser": True,
                "relative_cost": 3.5,
            }
        }
    )

    cluster_id: str
    tier: AgentTierEnum
    reason: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_browser: bool
    relative_cost: float = Field(
        default=1.0,
        description="Qualitative cost multiplier for one agent at this tier.",
        ge=0.0,
    )


class TierCounts(BaseModel):
    """Tier breakdown across the 52 consumer clusters."""

    MICRO: int = 0
    WORKER: int = 0
    SUPERVISOR: int = 0
    total: int = 0


class AgentRoutingRegistryOut(BaseModel):
    """Registry-wide rollup: tier counts + per-cluster routing decisions."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "generated_at": "2026-01-01T00:00:00Z",
                "tier_counts": {"MICRO": 7, "WORKER": 35, "SUPERVISOR": 10, "total": 52},
                "cost_summary": {
                    "MICRO": 7,
                    "WORKER": 35,
                    "SUPERVISOR": 10,
                    "total_equivalent_cost": 73.5,
                },
                "clusters": [],
            }
        }
    )

    generated_at: str
    tier_counts: TierCounts
    cost_summary: dict[str, float | int] = Field(
        default_factory=dict,
        description=(
            "Per-tier counts plus ``total_equivalent_cost`` — sum of "
            "(count × relative_cost) per tier, useful for estimating "
            "simulation runtime/budget."
        ),
    )
    clusters: list[AgentRoutingDecisionOut] = Field(default_factory=list)


__all__ = [
    "AgentTierEnum",
    "AgentRoutingDecisionOut",
    "TierCounts",
    "AgentRoutingRegistryOut",
    "TIER_RELATIVE_COST",
]