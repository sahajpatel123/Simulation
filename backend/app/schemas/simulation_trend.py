"""
Pydantic schemas for the simulation-trend analytics view
``GET /projects/{id}/simulation-trend``.

Builds on the existing ``simulation-history`` endpoint by surfacing derived
metrics: status breakdown, best/worst run details, volatility (std dev of
conversion rates), overall trend slope, and a 0..1 stability score.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunSummary(BaseModel):
    """One row in the history list — mirrors get_simulation_history shape."""

    simulation_id: int
    status: str
    signal_quality: float | None = None
    conversion_rate: float
    delta_from_prev: float | None = None
    direction: str | None = None
    created_at: str | None = None


class RunDetail(BaseModel):
    """Detail block for best/worst runs."""

    simulation_id: int
    conversion_rate: float
    signal_quality: float | None = None
    created_at: str | None = None
    status: str


class SimulationTrendOut(BaseModel):
    project_id: int
    total_runs: int = 0
    completed_runs: int = 0
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    history: list[RunSummary] = Field(default_factory=list)
    best_run: RunDetail | None = None
    worst_run: RunDetail | None = None
    latest_run: RunDetail | None = None
    conversion_stats: dict[str, float | None] = Field(default_factory=dict)
    trend_slope: float | None = None
    stability_score: float | None = None
    generated_at: str = ""


__all__ = [
    "RunSummary",
    "RunDetail",
    "SimulationTrendOut",
]
