"""
Pydantic schemas for the buyer-persona brief endpoint
``GET /simulations/{id}/buyer-personas``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BuyerPersona(BaseModel):
    """One cluster rendered as a founder-facing buyer persona."""

    cluster_id: str
    cluster_name: str = ""
    description: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    conversion_gap: float = 0.0
    opportunity_score: float = 0.0
    segment: str = "DEPRIORITIZE"
    estimated_lift: float = 0.0
    traits: dict[str, float] = Field(default_factory=dict)
    dominant_behavior_pattern: str = ""
    messaging_angle: str = ""
    product_affinities: list[str] = Field(default_factory=list)
    demographic_profile: dict[str, str] = Field(default_factory=dict)
    known_failure_modes: list[str] = Field(default_factory=list)
    risk_watch: list[str] = Field(default_factory=list)
    recommended_focus: str = ""


class BuyerPersonasOut(BaseModel):
    """Ranked buyer-persona briefs for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    signal_quality: float | None = None
    overall_conversion: float = 0.0
    total_agents: int = 0
    persona_count: int = 0
    primary_target_persona: str | None = None
    personas: list[BuyerPersona] = Field(default_factory=list)
    focus_recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = ["BuyerPersona", "BuyerPersonasOut"]
