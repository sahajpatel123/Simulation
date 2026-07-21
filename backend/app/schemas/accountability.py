"""
Pydantic schemas for accountability findings filtering, listing, and summary.

These schemas wrap the raw `domain_findings` dicts persisted on
`simulations.results_json` by `simulation_tasks.run_full_simulation`
(via AccountabilityEngine.generate_domain_findings().to_dict()).

They expose:

- ``DomainFindingOut`` — one ranked finding, fully typed.
- ``FindingsListOut`` — filtered / paginated list view.
- ``FindingsSummaryOut`` — group-by rollup for dashboards.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# Mirror of AccountabilityEngine ranking output. We keep severity as a free
# string here (rather than enum) because new severities may be introduced by
# future architect additions without requiring a coordinated schema bump.
VALID_SEVERITIES: frozenset[str] = frozenset({"CRITICAL", "WARNING", "INFO"})


class DomainFindingOut(BaseModel):
    """A single ranked architect × cluster finding persisted in results_json."""

    architect_name: str
    cluster_id: str
    cluster_name: str
    population_fraction: float
    finding: str
    metric_affected: str
    actual_value: float
    healthy_benchmark: float
    delta: float
    conversion_impact: float
    recommended_action: str
    affected_agent_count: int
    severity: str

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "DomainFindingOut":
        """
        Build a DomainFindingOut from the dict produced by
        ``DomainFinding.to_dict()``. Defensive defaults keep us resilient to
        older persisted payloads that may be missing newer keys.
        """
        return cls(
            architect_name=str(raw.get("architect_name", "unknown")),
            cluster_id=str(raw.get("cluster_id", "unknown")),
            cluster_name=str(raw.get("cluster_name", raw.get("cluster_id", "unknown"))),
            population_fraction=float(raw.get("population_fraction", 0.0) or 0.0),
            finding=str(raw.get("finding", "")),
            metric_affected=str(raw.get("metric_affected", "")),
            actual_value=float(raw.get("actual_value", 0.0) or 0.0),
            healthy_benchmark=float(raw.get("healthy_benchmark", 0.0) or 0.0),
            delta=float(raw.get("delta", raw.get("delta_from_benchmark", 0.0)) or 0.0),
            conversion_impact=float(raw.get("conversion_impact", 0.0) or 0.0),
            recommended_action=str(raw.get("recommended_action", "")),
            affected_agent_count=int(raw.get("affected_agent_count", 0) or 0),
            severity=str(raw.get("severity", "INFO")).upper(),
        )


class FindingsListOut(BaseModel):
    """Filtered, paginated list of ranked findings for a project."""

    project_id: int
    simulation_id: int | None = None
    primary_failure_domain: str = "unknown"
    highest_value_cluster: dict[str, Any] = Field(default_factory=dict)
    total: int = 0
    findings: list[DomainFindingOut] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class FindingsByArchitect(BaseModel):
    architect_name: str
    finding_count: int
    total_impact: float
    severity_breakdown: dict[str, int] = Field(default_factory=dict)
    rank: int


class FindingsByCluster(BaseModel):
    cluster_id: str
    cluster_name: str
    finding_count: int
    total_impact: float
    severity_breakdown: dict[str, int] = Field(default_factory=dict)


class FindingsByMetric(BaseModel):
    metric_affected: str
    finding_count: int
    total_impact: float
    severity_breakdown: dict[str, int] = Field(default_factory=dict)


class RecommendedActionCount(BaseModel):
    recommended_action: str
    count: int
    total_impact: float


class FindingsSummaryOut(BaseModel):
    """Group-by rollup suitable for a dashboard surface."""

    project_id: int = 0
    simulation_id: int | None = None
    total_findings: int = 0
    severity_breakdown: dict[str, int] = Field(default_factory=dict)
    primary_failure_domain: str = "unknown"
    highest_value_cluster: dict[str, Any] = Field(default_factory=dict)
    by_architect: list[FindingsByArchitect] = Field(default_factory=list)
    by_cluster: list[FindingsByCluster] = Field(default_factory=list)
    by_metric: list[FindingsByMetric] = Field(default_factory=list)
    recommended_actions: list[RecommendedActionCount] = Field(default_factory=list)
    top_critical_findings: list[DomainFindingOut] = Field(default_factory=list)


__all__ = [
    "VALID_SEVERITIES",
    "DomainFindingOut",
    "FindingsListOut",
    "FindingsByArchitect",
    "FindingsByCluster",
    "FindingsByMetric",
    "RecommendedActionCount",
    "FindingsSummaryOut",
]
