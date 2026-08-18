"""Pydantic schemas for the validation-momentum forecast endpoint.

``GET /projects/{project_id}/validation-momentum`` answers the pacing
question the evidence digest leaves open: not just *how much* risk has been
validated, but *how fast* it is being validated. The payload combines the
current coverage/de-risked counts with evidence cadence (experiments per
week, recent vs overall trend) and a projection of how many weeks — and
which calendar dates — remain until full coverage or a de-risked target is
reached.

The endpoint is deliberately simulation-independent (like the evidence
digest and validation timeline): a founder can track momentum before the
first simulation completes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ValidationMomentumCountsOut(BaseModel):
    """Current validation state for the project."""

    total_assumptions: int = Field(default=0, ge=0)
    total_evidence_rows: int = Field(default=0, ge=0)
    assumptions_with_evidence: int = Field(default=0, ge=0)
    de_risked_count: int = Field(default=0, ge=0)
    challenged_count: int = Field(default=0, ge=0)
    inconclusive_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    evidence_coverage_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_score: float | None = Field(default=None, ge=0.0, le=1.0)


class ValidationMomentumVelocityOut(BaseModel):
    """Evidence cadence metrics used to project de-risking speed.

    ``trend`` is one of:
    * ``NO_EVIDENCE`` — no logged experiments yet;
    * ``INSUFFICIENT`` — too few events (or all on one day) to compare pace;
    * ``ACCELERATING`` / ``STEADY`` / ``DECELERATING`` — recent 28-day
      cadence vs the overall cadence since the first experiment.
    """

    trend: str = "NO_EVIDENCE"
    overall_events_per_week: float | None = Field(default=None, ge=0.0)
    recent_events_per_week: float | None = Field(default=None, ge=0.0)
    recent_window_days: int = Field(default=28, ge=1)
    events_last_28_days: int = Field(default=0, ge=0)
    first_evidence_at: datetime | None = None
    latest_evidence_at: datetime | None = None
    evidence_span_days: float | None = Field(default=None, ge=0.0)
    coverage_velocity_per_week: float | None = Field(default=None, ge=0.0)
    de_risk_velocity_per_week: float | None = Field(default=None, ge=0.0)


class ValidationMomentumForecastOut(BaseModel):
    """Projected horizon to full evidence coverage / a de-risked target."""

    target_de_risked_pct: float = Field(default=1.0, ge=0.5, le=1.0)
    target_de_risked_count: int = Field(default=0, ge=0)
    remaining_for_coverage: int = Field(default=0, ge=0)
    remaining_for_target: int = Field(default=0, ge=0)
    weeks_to_full_coverage: float | None = Field(default=None, ge=0.0)
    projected_full_coverage_at: datetime | None = None
    weeks_to_de_risked_target: float | None = Field(default=None, ge=0.0)
    projected_de_risked_at: datetime | None = None
    confident: bool = False
    caveats: list[str] = Field(default_factory=list)


class ValidationMomentumOut(BaseModel):
    """Full response for the project validation-momentum endpoint."""

    project_id: int
    counts: ValidationMomentumCountsOut = Field(
        default_factory=ValidationMomentumCountsOut
    )
    velocity: ValidationMomentumVelocityOut = Field(
        default_factory=ValidationMomentumVelocityOut
    )
    forecast: ValidationMomentumForecastOut = Field(
        default_factory=ValidationMomentumForecastOut
    )
    insights: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ValidationMomentumCountsOut",
    "ValidationMomentumForecastOut",
    "ValidationMomentumOut",
    "ValidationMomentumVelocityOut",
]
