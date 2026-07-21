"""
Pydantic schemas for the cohort retention projection endpoint
``GET /api/v1/simulations/{id}/cohort-retention``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RetentionCurvePoint(BaseModel):
    """A single point on a cluster's retention curve."""

    day: int
    survival_rate: float = 0.0
    cumulative_churn: float = 0.0
    active_users: int = 0


class ClusterRetentionProfile(BaseModel):
    """Projected retention profile for a single cluster."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    agents_converted: int = 0
    retention_curve: list[RetentionCurvePoint] = Field(default_factory=list)
    day30_survival: float = 0.0
    day90_survival: float = 0.0
    churn_risk: str = "LOW"  # LOW | MEDIUM | HIGH | CRITICAL
    churn_trigger: str = ""
    ltv_score: float = 0.0
    ltv_estimate: float = 0.0
    reengagement_viable: bool = False
    reengagement_prob_30d: float = 0.0


class SegmentRetentionSummary(BaseModel):
    """Aggregated retention metrics for a churn-risk segment."""

    segment: str
    cluster_count: int = 0
    total_population_weight: float = 0.0
    mean_day30_survival: float = 0.0
    mean_day90_survival: float = 0.0
    mean_ltv_score: float = 0.0
    mean_churn_risk_score: float = 0.0


class CohortRetentionOut(BaseModel):
    """Full response for the cohort retention projection endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    overall_conversion: float = 0.0
    total_agents: int = 0
    total_converted: int = 0
    market_day30_survival: float = 0.0
    market_day90_survival: float = 0.0
    market_day365_survival: float = 0.0
    highest_churn_stage: str = ""
    best_retention_cluster: str = ""
    worst_retention_cluster: str = ""
    reengagement_viable: bool = False
    churn_trigger_distribution: dict[str, int] = Field(default_factory=dict)
    cluster_profiles: list[ClusterRetentionProfile] = Field(default_factory=list)
    segment_summary: list[SegmentRetentionSummary] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    product_type_detected: str = ""
    primary_failure_domain: str = ""
    signal_quality: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RetentionCurvePoint",
    "ClusterRetentionProfile",
    "SegmentRetentionSummary",
    "CohortRetentionOut",
]
