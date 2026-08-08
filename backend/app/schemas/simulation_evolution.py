"""Pydantic schemas for the per-project simulation-evolution endpoint.

``GET /projects/{project_id}/latest-sim-evolution`` compares the two most
recent completed simulations for one project and returns a founder-facing
digest: what changed in conversion, critical findings, and the funnel
bottleneck, plus the top recommendations from the latest run.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EvolutionRun(BaseModel):
    """Metadata + headline numbers for one side of the comparison."""

    simulation_id: int
    status: str = "COMPLETED"
    signal_quality: float | None = None
    conversion_rate: float | None = None
    critical_finding_count: int = 0
    bottleneck_stage: str | None = None
    created_at: str | None = None


class EvolutionFinding(BaseModel):
    """One finding that appeared or disappeared between the two runs."""

    domain: str = ""
    metric_affected: str = ""
    severity: str = "INFO"
    direction: str = "ADDED"  # ADDED | RESOLVED
    summary: str = ""


class EvolutionBottleneck(BaseModel):
    """Bottleneck movement between the previous and latest run."""

    previous: str | None = None
    latest: str | None = None
    changed: bool = False


class EvolutionConversion(BaseModel):
    """Predicted conversion movement between the two runs."""

    previous: float | None = None
    latest: float | None = None
    delta: float | None = None
    direction: str = "STABLE"  # IMPROVED | WORSENED | STABLE | NO_DATA


class EvolutionSummary(BaseModel):
    """Top-level movement narrative for the digest."""

    verdict: str = "NO_DATA"  # IMPROVED | WORSENED | STABLE | NO_DATA
    headline: str = ""
    narrative: str = ""


class EvolutionRecommendation(BaseModel):
    """One recommended next action from the latest run."""

    priority: int = 0
    title: str = ""
    summary: str = ""
    domain: str = ""
    source: str = "DOMAIN_FINDING"
    severity: str = "INFO"


class SimulationEvolutionOut(BaseModel):
    """Full response from ``GET /projects/{id}/latest-sim-evolution``."""

    project_id: int
    previous_run: EvolutionRun | None = None
    latest_run: EvolutionRun | None = None
    conversion: EvolutionConversion = Field(default_factory=EvolutionConversion)
    critical_findings: list[EvolutionFinding] = Field(default_factory=list)
    bottleneck: EvolutionBottleneck = Field(default_factory=EvolutionBottleneck)
    summary: EvolutionSummary = Field(default_factory=EvolutionSummary)
    recommendations: list[EvolutionRecommendation] = Field(default_factory=list)
    generated_at: str = ""


SimulationEvolutionOut.model_rebuild()


__all__ = [
    "EvolutionBottleneck",
    "EvolutionConversion",
    "EvolutionFinding",
    "EvolutionRecommendation",
    "EvolutionRun",
    "EvolutionSummary",
    "SimulationEvolutionOut",
]
