"""
Pydantic schemas for the journey-analytics endpoint
``GET /api/v1/simulations/{id}/journey``.

The payload answers founder questions the headline conversion number can't:
which stages consumers actually pass through, where they exit, the most
probable journeys, and which single transition improvement moves conversion
the most.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JourneyPathOut(BaseModel):
    """One most-probable journey through the funnel."""

    path: list[str]
    probability: float = Field(ge=0.0, le=1.0)
    converted: bool


class TransitionLeverageOut(BaseModel):
    """Expected conversion gain from improving one funnel transition by 5pp."""

    from_state: str
    to_state: str
    gain_per_5pp: float
    relative_gain_pct: float
    description: str


class ClusterJourneyOut(BaseModel):
    """Per-cluster journey summary.

    Besides the headline conversion probability, each cluster carries its
    expected per-stage leak distribution (where consumers in this segment
    abandon) and expected visits per stage before absorption — the detail a
    founder needs to see which segment's funnel is broken where.
    """

    cluster_id: str
    purchase_probability: float = Field(ge=0.0, le=1.0)
    expected_steps_to_absorb: float = Field(ge=0.0)
    primary_exit_stage: str | None = None
    exit_stage_distribution: dict[str, float] = Field(default_factory=dict)
    expected_visits_by_stage: dict[str, float] = Field(default_factory=dict)


class JourneyAnalyticsOut(BaseModel):
    """Full journey-analytics payload for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    purchase_probability: float = Field(ge=0.0, le=1.0)
    abandon_probability: float = Field(ge=0.0, le=1.0)
    expected_steps_to_absorb: float = Field(ge=0.0)
    expected_revisits: float = Field(ge=0.0)
    exit_stage_distribution: dict[str, float] = Field(default_factory=dict)
    top_paths: list[JourneyPathOut] = Field(default_factory=list)
    leverage_rankings: list[TransitionLeverageOut] = Field(default_factory=list)
    per_cluster: list[ClusterJourneyOut] = Field(default_factory=list)
    key_insights: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClusterJourneyOut",
    "JourneyAnalyticsOut",
    "JourneyPathOut",
    "TransitionLeverageOut",
]
