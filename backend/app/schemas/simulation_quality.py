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


__all__ = [
    "QualityCheck",
    "SimulationQualityOut",
    "SimulationQualitySummary",
]
