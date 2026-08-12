"""Pydantic schemas for the per-project outcome-feedback gaps digest.

The digest answers "which of my completed simulation runs still need
real-world feedback?" at the item level. A completed simulation only
teaches the calibration layer once a founder records an outcome against
it in ``founder_outcomes``; this surface turns the raw coverage counts
into an actionable, oldest-first list of unscored runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OutcomeGapUrgency = Literal["HIGH", "MEDIUM", "LOW"]


class SimulationOutcomeGapItem(BaseModel):
    """One completed simulation with no recorded founder outcome feedback."""

    simulation_id: int
    created_at: datetime
    age_days: int = Field(default=0, ge=0)
    signal_quality: float | None = None
    predicted_conversion_rate: float | None = None
    product_type_detected: str | None = None
    primary_failure_domain: str | None = None
    has_results: bool = False
    learning_eligible: bool = False
    urgency: OutcomeGapUrgency = "LOW"
    recommendation: str = ""


class ProjectOutcomeGapsSummary(BaseModel):
    """Rollup counts for the unscored-runs digest."""

    total_completed: int = Field(default=0, ge=0)
    scored: int = Field(default=0, ge=0)
    unscored: int = Field(default=0, ge=0)
    coverage_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    learning_eligible_unscored: int = Field(default=0, ge=0)
    oldest_unscored_age_days: int | None = Field(default=None, ge=0)
    narrative: str = ""


class ProjectOutcomeGapsOut(BaseModel):
    """Response from ``GET /projects/{project_id}/outcome-gaps``."""

    project_id: int
    generated_at: datetime
    summary: ProjectOutcomeGapsSummary
    items: list[SimulationOutcomeGapItem] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1)
    has_more: bool = False


__all__ = [
    "OutcomeGapUrgency",
    "ProjectOutcomeGapsOut",
    "ProjectOutcomeGapsSummary",
    "SimulationOutcomeGapItem",
]
