"""
Pydantic schemas for the funnel-bottleneck diagnosis endpoint
``GET /simulations/{id}/funnel-diagnosis``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StageDiagnosis(BaseModel):
    """Per-stage drop-off diagnosis against Markov healthy benchmarks."""

    stage: str
    agent_count: int = 0
    entry_rate: float = 0.0
    drop_off_rate: float = 0.0
    agents_lost: int = 0
    healthy_drop_off: float = 0.0
    delta_from_healthy: float = 0.0
    severity: str = "INFO"
    primary_domain: str = ""
    recommended_architects: list[str] = Field(default_factory=list)
    is_primary_bottleneck: bool = False


class ClusterDrag(BaseModel):
    """Cluster contribution to population-weighted conversion loss."""

    cluster_id: str
    cluster_name: str = ""
    conversion_rate: float = 0.0
    population_weight: float = 0.0
    lost_conversion_share: float = 0.0
    primary_drop_trigger: str | None = None
    mean_drop_state: str | None = None


class DropTriggerCount(BaseModel):
    """Aggregated primary_drop_trigger across cluster_run_summaries."""

    trigger: str
    cluster_count: int = 0
    agents_affected: int = 0
    mean_conversion: float = 0.0


class DiagnosisRecommendation(BaseModel):
    """Ranked intervention suggested by the diagnosis engine."""

    priority: int
    stage: str
    domain: str
    severity: str
    title: str
    rationale: str
    estimated_lift: float = 0.0
    architects: list[str] = Field(default_factory=list)
    related_clusters: list[str] = Field(default_factory=list)


class FunnelDiagnosisOut(BaseModel):
    """Full funnel bottleneck diagnosis payload."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    overall_conversion: float = 0.0
    total_agents: int = 0
    converted_agents: int = 0
    primary_bottleneck: str | None = None
    bottleneck_severity: str = "INFO"
    health_score: int = 0
    recoverable_conversion: float | None = None
    stages: list[StageDiagnosis] = Field(default_factory=list)
    cluster_drag: list[ClusterDrag] = Field(default_factory=list)
    drop_triggers: list[DropTriggerCount] = Field(default_factory=list)
    recommendations: list[DiagnosisRecommendation] = Field(default_factory=list)
    primary_failure_domain: str = "unknown"
    product_type_detected: str = ""
    signal_quality: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "StageDiagnosis",
    "ClusterDrag",
    "DropTriggerCount",
    "DiagnosisRecommendation",
    "FunnelDiagnosisOut",
]
