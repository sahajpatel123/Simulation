"""
Pydantic schemas for the journey-benchmark endpoints
``GET /api/v1/simulations/{id}/journey/benchmark`` and
``GET /api/v1/simulations/{id}/journey/category-benchmark``.

The payload compares one simulation's customer-journey funnel against the
reference cohort (the founder's other simulations, or all completed
simulations in the same product category): where the current idea ranks, how
its leaks compare with the cohort's norms, and what that means in plain
language.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JourneyBenchmarkCurrentOut(BaseModel):
    """Funnel summary for the simulation being benchmarked."""

    purchase_probability: float = Field(ge=0.0, le=1.0)
    abandon_probability: float = Field(ge=0.0, le=1.0)
    expected_steps_to_absorb: float = Field(ge=0.0)
    expected_revisits: float = Field(ge=0.0)
    primary_exit_stage: str | None = None
    exit_stage_distribution: dict[str, float] = Field(default_factory=dict)


class JourneyBenchmarkDistributionOut(BaseModel):
    """Cohort funnel statistics across the founder's other simulations."""

    median_purchase_probability: float | None = None
    mean_purchase_probability: float | None = None
    p25_purchase_probability: float | None = None
    p75_purchase_probability: float | None = None
    min_purchase_probability: float | None = None
    max_purchase_probability: float | None = None
    median_expected_steps: float | None = None
    median_expected_revisits: float | None = None
    most_common_primary_exit_stage: str | None = None
    stage_leak_medians: dict[str, float] = Field(default_factory=dict)


class JourneyBenchmarkOut(BaseModel):
    """Full journey-benchmark payload for a completed simulation."""

    simulation_id: int
    project_id: int
    cohort_size: int = Field(ge=0)
    current: JourneyBenchmarkCurrentOut
    distribution: JourneyBenchmarkDistributionOut = Field(
        default_factory=JourneyBenchmarkDistributionOut
    )
    percentile_rank: float | None = Field(default=None, ge=0.0, le=100.0)
    insights: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class JourneyCategoryBenchmarkOut(JourneyBenchmarkOut):
    """Category-scoped journey-benchmark payload for a completed simulation."""

    category: str


__all__ = [
    "JourneyBenchmarkCurrentOut",
    "JourneyBenchmarkDistributionOut",
    "JourneyBenchmarkOut",
    "JourneyCategoryBenchmarkOut",
]
