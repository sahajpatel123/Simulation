"""Pydantic schemas for the per-project conversion-tracking timeline.

The ``outcome_tracker`` table stores lightweight checkpoints a founder can
log over time (conversion / revenue at week 1, week 4, etc.) alongside the
predicted values from the project's latest simulation. These schemas cover
``POST /projects/{id}/outcome-tracker`` and
``GET /projects/{id}/outcome-tracker``.
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
    def _require_a_signal(self) -> "OutcomeTrackerCreate":
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


__all__ = [
    "OutcomeTrackerCreate",
    "OutcomeTrackerPoint",
    "OutcomeTrackerTimelineOut",
]
