"""
Pydantic schemas for the journey-trend endpoint
``GET /api/v1/simulations/{simulation_id}/journey/trend``.

The payload answers the question a founder asks after a few runs: *"am I
actually getting better at picking ideas?"* It turns every completed
simulation into a lightweight funnel summary (purchase probability, journey
length, revisits, primary exit stage) and surfaces the direction of travel:
per-point deltas, best/worst runs, an overall trend slope, stability, and
plain-language insights.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class JourneyTrendPointOut(BaseModel):
    """One simulation's funnel summary in the founder's journey history."""

    simulation_id: int
    project_id: int
    created_at: str | None = None
    purchase_probability: float = Field(ge=0.0, le=1.0)
    abandon_probability: float = Field(ge=0.0, le=1.0)
    expected_steps_to_absorb: float = Field(ge=0.0)
    expected_revisits: float = Field(ge=0.0)
    primary_exit_stage: str | None = None
    exit_stage_distribution: dict[str, float] = Field(default_factory=dict)
    delta_from_prev: float | None = None
    direction: str | None = None
    is_anchor: bool = False


class JourneyTrendSummaryOut(BaseModel):
    """Rolled-up funnel-health statistics across the founder's simulations."""

    included_count: int = Field(ge=0)
    raw_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    purchase_stats: dict[str, float | None] = Field(default_factory=dict)
    best_point: JourneyTrendPointOut | None = None
    worst_point: JourneyTrendPointOut | None = None
    trend_slope: float | None = None
    stability_score: float | None = None
    momentum: dict[str, float | int | None] = Field(default_factory=dict)
    most_common_primary_exit_stage: str | None = None
    stage_leak_medians: dict[str, float] = Field(default_factory=dict)
    latest_stage_leaks: dict[str, float] = Field(default_factory=dict)


class JourneyTrendOut(BaseModel):
    """Full journey-trend payload anchored on one completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    points: list[JourneyTrendPointOut] = Field(default_factory=list)
    summary: JourneyTrendSummaryOut = Field(
        default_factory=JourneyTrendSummaryOut
    )
    insights: list[str] = Field(default_factory=list)
    anchor_percentile_rank: float | None = Field(
        default=None, ge=0.0, le=100.0
    )
    generated_at: str = ""


__all__ = [
    "JourneyTrendOut",
    "JourneyTrendPointOut",
    "JourneyTrendSummaryOut",
]
