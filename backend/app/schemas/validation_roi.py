"""
Pydantic schemas for the validation-ROI endpoint
``GET /api/v1/simulations/{id}/validation-roi``.

Validation ROI answers "which assumption should I validate first?" by
combining how much an assumption can move conversion (sensitivity) with
how little evidence backs it today (uncertainty = 1 - confidence).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VALID_ROI_TIERS: frozenset[str] = frozenset(
    {"VALIDATE_FIRST", "HIGH_VALUE", "MONITOR", "LOW_VALUE"}
)


class AssumptionValidationRoi(BaseModel):
    """Validation-ROI ranking for a single assumption."""

    assumption_text: str = ""
    category: str = ""
    sensitivity_tier: str = "LOW"
    sensitivity_score: float = 0.0
    max_delta: float = 0.0
    confidence_tier: str = "DESIGN_INTENT"
    confidence_score: float = 0.0
    validation_roi: float = 0.0  # normalised 0-1: sensitivity x uncertainty
    roi_tier: str = "LOW_VALUE"
    expected_conversion_swing: float = 0.0
    recommendation: str = ""


class ValidationRoiSummary(BaseModel):
    """Aggregate summary of the validation-ROI analysis."""

    total_assumptions: int = 0
    baseline_conversion: float = 0.0
    avg_confidence: float = 0.0
    validated_assumptions: int = 0
    unvalidated_assumptions: int = 0
    validate_first_count: int = 0
    high_value_count: int = 0
    monitor_count: int = 0
    low_value_count: int = 0
    top_de_risking_assumption: str = ""
    top_roi_score: float = 0.0
    top_expected_swing: float = 0.0


class ValidationRoiOut(BaseModel):
    """Full response for the validation-ROI endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    baseline_conversion: float = 0.0
    signal_quality: float | None = None
    summary: ValidationRoiSummary
    assumptions: list[AssumptionValidationRoi] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VALID_ROI_TIERS",
    "AssumptionValidationRoi",
    "ValidationRoiSummary",
    "ValidationRoiOut",
]
