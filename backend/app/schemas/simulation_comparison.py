"""
Pydantic schemas for the simulation comparison / A/B endpoint
``POST /api/v1/simulations/compare``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SimulationCompareRequest(BaseModel):
    """Body for comparing 2–5 simulations from the same project."""

    simulation_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="Ordered list of 2–5 simulation IDs to compare",
    )

    @field_validator("simulation_ids")
    @classmethod
    def _unique_ids(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("simulation_ids must be unique")
        if any(i <= 0 for i in value):
            raise ValueError("simulation_ids must be positive integers")
        return value


class ComparisonSimulationRef(BaseModel):
    """Minimal reference to a simulation in the comparison set."""

    simulation_id: int
    status: str
    conversion_rate: float
    revenue_projection: float | None = None
    created_at: str
    signal_quality: float | None = None
    product_type_detected: str = ""


class ComparisonSummary(BaseModel):
    """Aggregate winner / spread / verdict block."""

    best_simulation_id: int
    best_conversion_rate: float
    worst_simulation_id: int
    worst_conversion_rate: float
    conversion_spread_pct: float
    revenue_spread_pct: float | None = None
    winner_label: str
    verdict: str


class ClusterComparisonRow(BaseModel):
    """One row in the per-cluster comparison table."""

    cluster_id: str
    cluster_name: str
    population_weight: float
    conversions: dict[int, float] = Field(
        default_factory=dict, description="simulation_id -> conversion_rate"
    )
    delta_from_best: dict[int, float] = Field(
        default_factory=dict, description="simulation_id -> delta vs best"
    )
    best_simulation_id: int
    winner_label: str


class DomainFindingComparison(BaseModel):
    """Side-by-side domain finding comparison across simulations."""

    domain: str
    findings: dict[int, list[dict[str, Any]]] = Field(
        default_factory=dict, description="simulation_id -> list of finding dicts"
    )
    severity_by_sim: dict[int, str | None] = Field(
        default_factory=dict, description="simulation_id -> highest severity or None"
    )
    consensus: str
    recommendation: str


class SimulationComparisonOut(BaseModel):
    """Full response for the simulation comparison endpoint."""

    project_id: int
    comparison_id: str
    simulations: list[ComparisonSimulationRef] = Field(default_factory=list)
    summary: ComparisonSummary
    cluster_comparison: list[ClusterComparisonRow] = Field(default_factory=list)
    domain_finding_comparison: list[DomainFindingComparison] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: str = ""


__all__ = [
    "SimulationCompareRequest",
    "ComparisonSimulationRef",
    "ComparisonSummary",
    "ClusterComparisonRow",
    "DomainFindingComparison",
    "SimulationComparisonOut",
]
