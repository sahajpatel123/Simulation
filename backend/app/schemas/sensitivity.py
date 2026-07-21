"""
Pydantic schemas for the scenario sensitivity analysis endpoint
``GET /api/v1/simulations/{id}/sensitivity``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SensitivityPoint(BaseModel):
    """A single point on an assumption's sensitivity curve."""

    impact_score: float = 0.0
    conversion_rate: float = 0.0
    delta_from_baseline: float = 0.0


class AssumptionSensitivity(BaseModel):
    """Sensitivity analysis result for a single assumption."""

    assumption_text: str = ""
    sensitivity: str = "MEDIUM"
    baseline_impact_score: float = 0.0
    baseline_conversion: float = 0.0
    max_delta: float = 0.0
    sensitivity_score: float = 0.0  # normalised 0–1
    sensitivity_tier: str = "LOW"  # CRITICAL | HIGH | MEDIUM | LOW
    curve: list[SensitivityPoint] = Field(default_factory=list)
    triggers_markov_rules: bool = False
    affected_transitions: list[str] = Field(default_factory=list)
    recommendation: str = ""


class SensitivitySummary(BaseModel):
    """Aggregate summary of the sensitivity analysis."""

    total_assumptions: int = 0
    baseline_conversion: float = 0.0
    most_sensitive_assumption: str = ""
    most_sensitive_score: float = 0.0
    critical_assumptions: int = 0
    high_assumptions: int = 0
    medium_assumptions: int = 0
    low_assumptions: int = 0
    avg_sensitivity_score: float = 0.0


class SensitivityOut(BaseModel):
    """Full response for the scenario sensitivity analysis endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    baseline_conversion: float = 0.0
    baseline_revenue_per_1000: float = 0.0
    summary: SensitivitySummary
    assumptions: list[AssumptionSensitivity] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    product_type_detected: str = ""
    signal_quality: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "SensitivityPoint",
    "AssumptionSensitivity",
    "SensitivitySummary",
    "SensitivityOut",
]
