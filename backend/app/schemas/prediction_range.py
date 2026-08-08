"""
Pydantic schemas for the prediction-range digest endpoint
``GET /api/v1/simulations/{id}/prediction-range``.

The digest answers a founder question the headline number can't: *how much
should I trust this conversion prediction?* It blends the run's predicted
conversion rate with historical (predicted, actual) outcome pairs and emits a
realistic low/high band plus a calibration label.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
LABEL_WELL_CALIBRATED: str = "WELL_CALIBRATED"
LABEL_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
LABEL_POORLY_CALIBRATED: str = "POORLY_CALIBRATED"

VALID_CONFIDENCE_LABELS: frozenset[str] = frozenset({
    LABEL_INSUFFICIENT_DATA,
    LABEL_WELL_CALIBRATED,
    LABEL_NEEDS_ATTENTION,
    LABEL_POORLY_CALIBRATED,
})


class PredictionRangeKeySignal(BaseModel):
    """One named key signal in the digest payload."""

    label: str
    value: Any = None
    severity: str = "info"


class PredictionRangeOut(BaseModel):
    """Full accuracy-adjusted prediction-range payload."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    predicted_conversion_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    low: float | None = Field(default=None, ge=0.0, le=1.0)
    high: float | None = Field(default=None, ge=0.0, le=1.0)
    spread: float | None = Field(default=None, ge=0.0, le=1.0)
    mae: float | None = Field(default=None, ge=0.0, le=1.0)
    rmse: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_sample_count: int = Field(default=0, ge=0)
    calibration_source: str = "none"
    confidence_label: str = LABEL_INSUFFICIENT_DATA
    narrative: str = ""
    key_signals: list[PredictionRangeKeySignal] = Field(
        default_factory=list
    )
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "LABEL_INSUFFICIENT_DATA",
    "LABEL_NEEDS_ATTENTION",
    "LABEL_POORLY_CALIBRATED",
    "LABEL_WELL_CALIBRATED",
    "VALID_CONFIDENCE_LABELS",
    "PredictionRangeKeySignal",
    "PredictionRangeOut",
]
