"""
Pydantic schemas for the validation-ROI endpoint
``GET /api/v1/simulations/{id}/validation-roi``.

Validation ROI answers "which assumption should I validate first?" by
combining how much an assumption can move conversion (sensitivity) with
how little evidence backs it today (uncertainty = 1 - confidence).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

VALID_ROI_TIERS: frozenset[str] = frozenset(
    {"VALIDATE_FIRST", "HIGH_VALUE", "MONITOR", "LOW_VALUE"}
)

ROI_TIER_LITERAL = Literal["VALIDATE_FIRST", "HIGH_VALUE", "MONITOR", "LOW_VALUE"]
CONFIDENCE_TIER_LITERAL = Literal[
    "VALIDATED_EXTERNAL", "VALIDATED_INTERNAL", "DESIGN_INTENT", "ASPIRATIONAL"
]
SENSITIVITY_TIER_LITERAL = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class AssumptionValidationRoi(BaseModel):
    """Validation-ROI ranking for a single assumption."""

    assumption_text: str = ""
    category: str = ""
    sensitivity_tier: SENSITIVITY_TIER_LITERAL = "LOW"
    sensitivity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    max_delta: float = 0.0
    confidence_tier: CONFIDENCE_TIER_LITERAL = "DESIGN_INTENT"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_roi: float = Field(  # normalised 0-1: sensitivity x uncertainty
        default=0.0, ge=0.0, le=1.0
    )
    roi_tier: ROI_TIER_LITERAL = "LOW_VALUE"
    expected_conversion_swing: float = Field(default=0.0, ge=0.0, le=1.0)
    recommendation: str = ""


class ValidationRoiSummary(BaseModel):
    """Aggregate summary of the validation-ROI analysis."""

    total_assumptions: int = Field(default=0, ge=0)
    baseline_conversion: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validated_assumptions: int = Field(default=0, ge=0)
    unvalidated_assumptions: int = Field(default=0, ge=0)
    validate_first_count: int = Field(default=0, ge=0)
    high_value_count: int = Field(default=0, ge=0)
    monitor_count: int = Field(default=0, ge=0)
    low_value_count: int = Field(default=0, ge=0)
    top_de_risking_assumption: str = ""
    top_roi_score: float = Field(default=0.0, ge=0.0, le=1.0)
    top_expected_swing: float = Field(default=0.0, ge=0.0, le=1.0)


class ValidationRoiOut(BaseModel):
    """Full response for the validation-ROI endpoint."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    baseline_conversion: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
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
