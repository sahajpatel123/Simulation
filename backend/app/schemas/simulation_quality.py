"""
Pydantic schemas for the simulation quality gate
``GET /api/v1/simulations/{id}/quality``.

The gate answers "how trustworthy are these numbers?" by running a
deterministic integrity check over a completed run's persisted results:
cluster coverage, conversion-rate bounds, funnel sanity, weighted-blend
consistency and NaN/Inf freedom. Output is a 0..1 ``trust_score`` with a
PASS / REVIEW / FAIL verdict plus per-check detail.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SEVERITY_LITERAL = Literal["CRITICAL", "MAJOR", "MINOR", "INFO"]
VERDICT_LITERAL = Literal["PASS", "REVIEW", "FAIL"]
PROJECT_VERDICT_LITERAL = Literal["PASS", "REVIEW", "FAIL", "INSUFFICIENT_DATA"]


class QualityCheck(BaseModel):
    """Result of a single quality check."""

    id: str
    label: str
    severity: SEVERITY_LITERAL = "MINOR"
    passed: bool | None = None
    skipped: bool = False
    detail: str = ""


class SimulationQualitySummary(BaseModel):
    """Aggregate counts for the quality gate run."""

    total_checks: int = Field(default=0, ge=0)
    evaluated_checks: int = Field(default=0, ge=0)
    passed_checks: int = Field(default=0, ge=0)
    failed_checks: int = Field(default=0, ge=0)
    skipped_checks: int = Field(default=0, ge=0)


class SimulationQualityOut(BaseModel):
    """Full response for the simulation quality gate."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    trust_score: float = Field(default=0.0, ge=0.0, le=1.0)
    verdict: VERDICT_LITERAL = "REVIEW"
    headline_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: SimulationQualitySummary
    checks: list[QualityCheck] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class ProjectSimulationQualityRow(BaseModel):
    """One simulation's quality-gate result in the project digest."""

    simulation_id: int
    status: str = ""
    created_at: str | None = None
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    verdict: VERDICT_LITERAL | None = None
    headline_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    failed_checks: int = Field(default=0, ge=0)
    skipped_checks: int = Field(default=0, ge=0)


class ProjectSimulationQualityOut(BaseModel):
    """Response from ``GET /projects/{id}/simulation-quality``.

    Rolls the per-run quality gate over a project's simulation history so a
    founder can answer "how trustworthy is this project's simulation record?"
    without opening each run's full quality report.
    """

    project_id: int
    total_runs: int = Field(default=0, ge=0)
    completed_runs: int = Field(default=0, ge=0)
    evaluated_runs: int = Field(default=0, ge=0)
    pass_count: int = Field(default=0, ge=0)
    review_count: int = Field(default=0, ge=0)
    fail_count: int = Field(default=0, ge=0)
    overall_verdict: PROJECT_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    mean_trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    min_trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    generated_at: str = ""
    runs: list[ProjectSimulationQualityRow] = Field(default_factory=list)


__all__ = [
    "PROJECT_VERDICT_LITERAL",
    "ProjectSimulationQualityOut",
    "ProjectSimulationQualityRow",
    "QualityCheck",
    "SimulationQualityOut",
    "SimulationQualitySummary",
]
