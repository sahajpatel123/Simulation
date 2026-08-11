"""Pydantic schemas for the prediction-range coverage digest.

``GET /api/v1/projects/{project_id}/prediction-range-coverage`` answers a
question the single-run prediction-range endpoint cannot: **how often did the
accuracy-adjusted band actually contain the recorded outcome?** Each project
outcome is evaluated out-of-sample — the band is rebuilt from history
available *before* that outcome was recorded, using the same calibration
source fallback (project pairs first, then the user pool) as the live
endpoint.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VERDICT_WELL_CALIBRATED: str = "WELL_CALIBRATED"
VERDICT_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
VERDICT_POORLY_CALIBRATED: str = "POORLY_CALIBRATED"

VALID_VERDICTS: frozenset[str] = frozenset({
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_WELL_CALIBRATED,
    VERDICT_NEEDS_ATTENTION,
    VERDICT_POORLY_CALIBRATED,
})


class PredictionRangeCoverageRow(BaseModel):
    """One out-of-sample band check for a project outcome."""

    simulation_id: int | None = None
    project_id: int = 0
    predicted_conversion_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    actual_conversion_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    low: float | None = Field(default=None, ge=0.0, le=1.0)
    high: float | None = Field(default=None, ge=0.0, le=1.0)
    history_count: int = Field(default=0, ge=0)
    calibration_source: str = "none"
    confidence_label: str = "INSUFFICIENT_DATA"
    within: bool | None = None
    margin: float | None = Field(default=None, ge=0.0)
    evaluated: bool = False
    created_at: str | None = None


class PredictionRangeCoverageKeySignal(BaseModel):
    """One named key signal in the coverage digest."""

    label: str
    value: Any = None
    severity: str = "info"
    display: str = ""


class PredictionRangeCoverageOut(BaseModel):
    """Response from ``GET /projects/{id}/prediction-range-coverage``."""

    project_id: int = Field(default=0, ge=0)
    generated_at: str = ""
    total_project_outcomes: int = Field(default=0, ge=0)
    evaluated_runs: int = Field(default=0, ge=0)
    within_range_count: int = Field(default=0, ge=0)
    coverage_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_margin: float | None = Field(default=None, ge=0.0)
    worst_miss: dict[str, Any] | None = None
    verdict: str = VERDICT_INSUFFICIENT_DATA
    narrative: str = ""
    key_signals: list[PredictionRangeCoverageKeySignal] = Field(
        default_factory=list
    )
    rows: list[PredictionRangeCoverageRow] = Field(default_factory=list)


__all__ = [
    "VALID_VERDICTS",
    "VERDICT_INSUFFICIENT_DATA",
    "VERDICT_NEEDS_ATTENTION",
    "VERDICT_POORLY_CALIBRATED",
    "VERDICT_WELL_CALIBRATED",
    "PredictionRangeCoverageKeySignal",
    "PredictionRangeCoverageOut",
    "PredictionRangeCoverageRow",
]
