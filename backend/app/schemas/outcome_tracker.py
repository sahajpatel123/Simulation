"""Pydantic schemas for the per-project conversion-tracking features.

The ``outcome_tracker`` table stores lightweight checkpoints a founder can
log over time (conversion / revenue at week 1, week 4, etc.) alongside the
predicted values from the project's latest simulation. These schemas cover
``POST /projects/{id}/outcome-tracker`` and
``GET /projects/{id}/outcome-tracker``, plus the trajectory forecast at
``GET /projects/{id}/outcome-tracker/forecast``.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class OutcomeTrackerCreate(BaseModel):
    """Body for logging a conversion-tracking checkpoint.

    At least one of ``actual_conversion_rate`` / ``actual_revenue`` must be
    provided so a point always carries a useful signal. ``simulation_id`` is
    optional — when omitted the route attaches the project's latest completed
    simulation automatically.
    """

    model_config = {"extra": "forbid"}

    simulation_id: int | None = Field(default=None, ge=1)
    actual_conversion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    actual_revenue: float | None = Field(default=None, ge=0.0)
    recorded_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_a_signal(self) -> OutcomeTrackerCreate:
        if (
            self.actual_conversion_rate is None
            and self.actual_revenue is None
        ):
            raise ValueError(
                "Provide at least one of actual_conversion_rate or actual_revenue"
            )
        return self


class OutcomeTrackerPoint(BaseModel):
    """One stored tracking checkpoint."""

    id: int
    project_id: int
    simulation_id: int | None = None
    recorded_at: datetime | None = None
    actual_conversion_rate: float | None = None
    actual_revenue: float | None = None
    predicted_conversion_rate: float | None = None
    predicted_revenue: float | None = None
    variance: float | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class OutcomeTrackerTimelineOut(BaseModel):
    """Full timeline payload for GET /projects/{id}/outcome-tracker."""

    project_id: int
    total_points: int = 0
    points: list[OutcomeTrackerPoint] = Field(default_factory=list)
    latest_predicted: float | None = None
    latest_actual: float | None = None
    latest_revenue: float | None = None
    latest_predicted_revenue: float | None = None
    latest_variance_pct: float | None = None
    mean_abs_variance_pct: float | None = None
    bias_direction: str = "INSUFFICIENT_DATA"


class OutcomeTrackerForecastPoint(BaseModel):
    """One horizon in the trajectory forecast."""

    horizon_days: int
    projected_conversion_rate: float


class OutcomeTrackerForecastOut(BaseModel):
    """Trajectory forecast payload for GET /projects/{id}/outcome-tracker/forecast."""

    project_id: int
    sample_count: int = 0
    span_days: float | None = None
    latest_actual: float | None = None
    predicted_conversion_rate: float | None = None
    ceiling_conversion_rate: float | None = None
    slope_per_day: float | None = None
    r_squared: float | None = None
    trend_label: str = "INSUFFICIENT_DATA"
    confidence: str = "INSUFFICIENT_DATA"
    verdict: str = "INSUFFICIENT_DATA"
    forecasts: list[OutcomeTrackerForecastPoint] = Field(default_factory=list)
    days_to_target: float | None = None
    narrative: str = ""
    key_signals: list[dict] = Field(default_factory=list)


class OutcomeTrackerRevenueForecastPoint(BaseModel):
    """One horizon in the revenue trajectory forecast."""

    horizon_days: int
    projected_revenue: float


class OutcomeTrackerRevenueForecastOut(BaseModel):
    """Revenue trajectory forecast payload for the revenue-forecast endpoint."""

    project_id: int
    sample_count: int = 0
    span_days: float | None = None
    latest_revenue: float | None = None
    predicted_revenue: float | None = None
    ceiling_revenue: float | None = None
    slope_per_day: float | None = None
    r_squared: float | None = None
    trend_label: str = "INSUFFICIENT_DATA"
    confidence: str = "INSUFFICIENT_DATA"
    verdict: str = "INSUFFICIENT_DATA"
    forecasts: list[OutcomeTrackerRevenueForecastPoint] = Field(default_factory=list)
    days_to_target: float | None = None
    narrative: str = ""
    key_signals: list[dict] = Field(default_factory=list)


class OutcomeTrackerForecastAccuracyPoint(BaseModel):
    """One horizon's historical forecast-accuracy summary."""

    horizon_days: int
    sample_count: int = 0
    mean_abs_error: float | None = None
    mean_abs_pct_error: float | None = None
    bias: float | None = None
    bias_direction: str = "INSUFFICIENT_DATA"
    accuracy_score: float | None = None
    within_2pp_rate: float | None = None


class OutcomeTrackerForecastAccuracyOut(BaseModel):
    """Forecast-reliability payload for GET /projects/{id}/outcome-tracker/forecast-accuracy."""

    project_id: int
    total_verifications: int = 0
    overall_accuracy_score: float | None = None
    overall_mean_abs_error: float | None = None
    overall_bias: float | None = None
    overall_bias_direction: str = "INSUFFICIENT_DATA"
    overall_verdict: str = "INSUFFICIENT_DATA"
    confidence: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    horizons: list[OutcomeTrackerForecastAccuracyPoint] = Field(default_factory=list)


class OutcomeTrackerDriftCheck(BaseModel):
    """One tracked step: the model's expected conversion vs what was logged."""

    expected_conversion_rate: float
    actual_conversion_rate: float
    deviation_pp: float
    days_since_first: float
    gap_days: float


class OutcomeTrackerDriftOut(BaseModel):
    """Tracking-drift payload for GET /projects/{id}/outcome-tracker/drift."""

    project_id: int
    sample_count: int = 0
    span_days: float | None = None
    latest_actual: float | None = None
    predicted_conversion_rate: float | None = None
    mean_tracking_error_pp: float | None = None
    mean_abs_tracking_error_pp: float | None = None
    latest_tracking_error_pp: float | None = None
    tracking_status: str = "INSUFFICIENT_DATA"
    gap_slope_pp_per_check: float | None = None
    drift_direction: str = "INSUFFICIENT_DATA"
    severity: str = "watch"
    narrative: str = ""
    checks: list[OutcomeTrackerDriftCheck] = Field(default_factory=list)


__all__ = [
    "OutcomeTrackerCreate",
    "OutcomeTrackerPoint",
    "OutcomeTrackerTimelineOut",
    "OutcomeTrackerForecastPoint",
    "OutcomeTrackerForecastOut",
    "OutcomeTrackerRevenueForecastPoint",
    "OutcomeTrackerRevenueForecastOut",
    "OutcomeTrackerForecastAccuracyPoint",
    "OutcomeTrackerForecastAccuracyOut",
    "OutcomeTrackerDriftCheck",
    "OutcomeTrackerDriftOut",
]
