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

from pydantic import BaseModel, Field


class AgentTierEnum(str, Enum):
    """Public mirror of ``app.simulation.agent_hierarchy.AgentTier``."""

    MICRO = "MICRO"
    WORKER = "WORKER"
    SUPERVISOR = "SUPERVISOR"


class AgentRoutingDecisionOut(BaseModel):
    """One cluster's routing decision."""

    cluster_id: str
    tier: AgentTierEnum
    reason: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_browser: bool


class TierCounts(BaseModel):
    """Tier breakdown across the 52 consumer clusters."""

    MICRO: int = 0
    WORKER: int = 0
    SUPERVISOR: int = 0
    total: int = 0


class AgentRoutingRegistryOut(BaseModel):
    """Registry-wide rollup: tier counts + per-cluster routing decisions."""

    generated_at: str
    tier_counts: TierCounts
    clusters: list[AgentRoutingDecisionOut] = Field(default_factory=list)


__all__ = [
    "AgentTierEnum",
    "AgentRoutingDecisionOut",
    "TierCounts",
    "AgentRoutingRegistryOut",
]