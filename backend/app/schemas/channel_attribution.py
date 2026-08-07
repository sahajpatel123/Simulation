"""
Pydantic schemas for the channel-attribution read
``GET /api/v1/simulations/{id}/channel-attribution``.

The endpoint turns the existing ``ChannelAttributionEngine`` into a
founder-facing acquisition read: per-cluster channel scores, the
population-weighted market channel ranking, the lowest-CAC channel,
and a recommended budget-mix split. It is deterministic and does not
require a generated UI run — any completed simulation can ask "which
channels should I start with and how should I split early spend?".
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChannelRanking(BaseModel):
    """One channel's population-weighted market score."""

    channel: str
    weighted_score: float = 0.0


class ChannelClusterProfile(BaseModel):
    """One cluster's channel-attribution profile."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    primary_channel: str = ""
    secondary_channel: str = ""
    cac_multiplier: float = 1.0
    viral_coefficient: float = 0.0
    wom_strength: float = 0.0
    paid_receptivity: float = 0.0
    influencer_dependency: float = 0.0
    channel_scores: dict[str, float] = Field(default_factory=dict)


class ChannelAttributionOut(BaseModel):
    """Full channel-attribution response for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    highest_roi_channel: str = ""
    lowest_cac_channel: str = ""
    viral_growth_possible: bool = False
    recommended_channel_mix: dict[str, float] = Field(default_factory=dict)
    market_channel_ranking: list[ChannelRanking] = Field(default_factory=list)
    cluster_profiles: list[ChannelClusterProfile] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ChannelAttributionOut",
    "ChannelClusterProfile",
    "ChannelRanking",
]
