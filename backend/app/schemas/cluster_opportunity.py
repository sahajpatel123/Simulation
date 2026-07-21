"""
Pydantic schemas for the cluster opportunity matrix endpoint
``GET /simulations/{id}/cluster-opportunities``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VALID_SEGMENTS: frozenset[str] = frozenset(
    {"QUICK_WIN", "TRANSFORM", "NICHE", "DEPRIORITIZE"}
)


class ClusterOpportunity(BaseModel):
    """One cluster ranked by addressable conversion opportunity."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    conversion_gap: float = 0.0
    opportunity_score: float = 0.0
    segment: str = "DEPRIORITIZE"
    estimated_lift: float = 0.0
    primary_drop_trigger: str | None = None
    mean_drop_state: str | None = None
    agents_assigned: int | None = None
    agents_converted: int | None = None
    recommended_action: str = ""


class SegmentBucket(BaseModel):
    """Rollup counts and total opportunity mass per segment."""

    segment: str
    cluster_count: int = 0
    total_opportunity: float = 0.0
    total_population_weight: float = 0.0
    mean_conversion: float | None = None


class ClusterOpportunityMatrixOut(BaseModel):
    """Full cluster opportunity matrix for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    overall_conversion: float = 0.0
    total_agents: int = 0
    addressable_lift: float = 0.0
    top_opportunity_cluster: str | None = None
    opportunities: list[ClusterOpportunity] = Field(default_factory=list)
    segment_breakdown: list[SegmentBucket] = Field(default_factory=list)
    focus_recommendations: list[str] = Field(default_factory=list)
    product_type_detected: str = ""
    primary_failure_domain: str = "unknown"
    signal_quality: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VALID_SEGMENTS",
    "ClusterOpportunity",
    "SegmentBucket",
    "ClusterOpportunityMatrixOut",
]
