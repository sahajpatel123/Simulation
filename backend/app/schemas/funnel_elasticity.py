"""
Pydantic schemas for the funnel-elasticity endpoint
``GET /api/v1/simulations/{id}/funnel-elasticity``.

While journey analytics answers "which 5pp nudge moves conversion most",
this payload answers the founder's real question: *which behavioural
transition is worth improving, by how much, and does my audience actually
agree?* It exposes loop-adjusted conversion (absorbing-chain solve vs the
naive stage-product headline), per-edge lift/headroom/elasticity, and the
population-weighted cluster consensus behind the ranking.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ElasticityEdgeOut(BaseModel):
    """One forward funnel edge and how much improving it can buy."""

    from_state: str
    to_state: str
    lift_per_gain_pp: float = Field(ge=0.0)
    headroom_lift_pp: float = Field(ge=0.0)
    elasticity: float | None = None
    related_keywords: list[str] = Field(default_factory=list)
    rank: int = Field(ge=1)


class ClusterConsensusOut(BaseModel):
    """Weighted vote share of clusters ranking an edge their top lever."""

    edge: str
    weighted_vote_share: float = Field(ge=0.0, le=1.0)


class PerClusterTopEdgeOut(BaseModel):
    """Per-cluster drill-down: which edge this segment wants fixed first."""

    cluster_id: str
    population_weight: float = Field(gt=0.0)
    loop_adjusted_conversion: float = Field(ge=0.0, le=1.0)
    top_edge: str
    top_lift_pp: float = Field(ge=0.0)


class FunnelElasticityOut(BaseModel):
    """Population-level funnel transition elasticity for a simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    naive_conversion: float = Field(ge=0.0, le=1.0)
    loop_adjusted_conversion: float = Field(ge=0.0, le=1.0)
    loop_uplift_pp: float = Field(ge=0.0)
    edges: list[ElasticityEdgeOut] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    cluster_consensus: list[ClusterConsensusOut] = Field(default_factory=list)
    per_cluster_top_edges: list[PerClusterTopEdgeOut] = Field(default_factory=list)
    recommendation: str
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ElasticityEdgeOut",
    "ClusterConsensusOut",
    "PerClusterTopEdgeOut",
    "FunnelElasticityOut",
]
