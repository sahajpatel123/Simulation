"""
Pydantic schemas for the real-world outcome peer benchmark
``GET /api/v1/projects/{id}/outcome-benchmark``.

The endpoint ranks a project's reported actual conversion rate against peer
outcomes from other launched projects in the same product category. This
module defines the response contract for that payload.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OutcomeBenchmarkCurrentOut(BaseModel):
    """The project's most recent reported founder outcome."""

    outcome_id: int = Field(ge=1)
    simulation_id: int | None = None
    project_id: int = Field(ge=1)
    actual_conversion_rate: float = Field(ge=0.0, le=1.0)
    predicted_conversion_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    days_since_launch: int = Field(ge=0)
    data_confidence: str | None = None
    launched: bool = False
    recorded_at: str | None = None


class OutcomeBenchmarkDistributionOut(BaseModel):
    """Peer-outcome distribution statistics."""

    peer_count: int = Field(ge=0)
    min: float | None = Field(default=None, ge=0.0, le=1.0)
    p25: float | None = Field(default=None, ge=0.0, le=1.0)
    median: float | None = Field(default=None, ge=0.0, le=1.0)
    p75: float | None = Field(default=None, ge=0.0, le=1.0)
    max: float | None = Field(default=None, ge=0.0, le=1.0)
    mean: float | None = Field(default=None, ge=0.0, le=1.0)


class OutcomeBenchmarkOut(BaseModel):
    """Full real-world outcome peer-benchmark payload."""

    has_data: bool = False
    category: str | None = None
    current: OutcomeBenchmarkCurrentOut | None = None
    distribution: OutcomeBenchmarkDistributionOut = Field(
        default_factory=OutcomeBenchmarkDistributionOut
    )
    percentile_rank: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )
    verdict: str = "INSUFFICIENT_DATA"
    median_comparison: str | None = None
    narrative: str = ""
    insights: list[str] = Field(default_factory=list)
    key_signals: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "OutcomeBenchmarkCurrentOut",
    "OutcomeBenchmarkDistributionOut",
    "OutcomeBenchmarkOut",
]
