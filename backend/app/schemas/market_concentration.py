"""
Pydantic schemas for the demand-concentration endpoint
``GET /simulations/{id}/market-concentration``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VALID_VERDICTS: frozenset[str] = frozenset(
    {"DIVERSIFIED", "MODERATE", "CONCENTRATED", "INSUFFICIENT_DATA"}
)


class ClusterDemandShare(BaseModel):
    """One cluster's share of projected conversion demand."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    demand_share: float = 0.0
    cumulative_share: float = 0.0


class MarketConcentrationOut(BaseModel):
    """Full demand-concentration read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    signal_quality: float | None = None
    total_conversion_rate: float = 0.0
    hhi: float = 0.0
    normalized_hhi: float = 0.0
    effective_segments: float = 0.0
    verdict: str = "INSUFFICIENT_DATA"
    top_1_share: float = 0.0
    top_3_share: float = 0.0
    top_5_share: float = 0.0
    top_cluster_id: str | None = None
    top_cluster_name: str = ""
    total_clusters: int = 0
    clusters_with_demand: int = 0
    fragility_flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    segment_shares: list[ClusterDemandShare] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VALID_VERDICTS",
    "ClusterDemandShare",
    "MarketConcentrationOut",
]
