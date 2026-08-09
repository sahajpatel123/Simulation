"""Pydantic schemas for the admin pipeline-timing analytics endpoint.

``GET /api/v1/analytics/pipeline-timing`` aggregates the per-stage
wall-clock payloads persisted in ``results_json["pipeline_timing"]`` across
recent completed simulations so operators can see fleet-wide stage
distributions and the slowest runs in one response.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PipelineStageStats(BaseModel):
    """Aggregate statistics for one pipeline stage across sampled runs."""

    stage: str
    runs: int = Field(default=0, ge=0)
    mean_seconds: float | None = Field(default=None, ge=0.0)
    median_seconds: float | None = Field(default=None, ge=0.0)
    p95_seconds: float | None = Field(default=None, ge=0.0)
    max_seconds: float | None = Field(default=None, ge=0.0)
    mean_share: float | None = Field(default=None, ge=0.0, le=1.0)


class PipelineTimingTotals(BaseModel):
    """Fleet totals across the sampled runs' timing payloads."""

    runs: int = Field(default=0, ge=0)
    mean_seconds: float | None = Field(default=None, ge=0.0)
    median_seconds: float | None = Field(default=None, ge=0.0)
    p95_seconds: float | None = Field(default=None, ge=0.0)
    max_seconds: float | None = Field(default=None, ge=0.0)
    sum_seconds: float | None = Field(default=None, ge=0.0)
    mean_per_agent_ms: float | None = Field(default=None, ge=0.0)
    p95_per_agent_ms: float | None = Field(default=None, ge=0.0)
    mean_end_to_end_seconds: float | None = Field(default=None, ge=0.0)


class PipelineTimingRun(BaseModel):
    """One sampled run, enriched for slow-run triage."""

    simulation_id: int
    project_id: int
    created_at: datetime | None = None
    total_seconds: float | None = Field(default=None, ge=0.0)
    per_agent_ms: float | None = Field(default=None, ge=0.0)
    end_to_end_seconds: float | None = Field(default=None, ge=0.0)
    dominant_stage: str | None = None
    stages: dict[str, float] = Field(default_factory=dict)


class PipelineTimingSummaryOut(BaseModel):
    """Full response for ``GET /api/v1/analytics/pipeline-timing``."""

    generated_at: datetime
    sample_limit: int | None = Field(default=None, ge=1)
    total_completed: int | None = Field(default=None, ge=0)
    with_timing: int | None = Field(default=None, ge=0)
    coverage_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    runs_analysed: int = Field(default=0, ge=0)
    totals: PipelineTimingTotals
    stages: list[PipelineStageStats] = Field(default_factory=list)
    slowest_runs: list[PipelineTimingRun] = Field(default_factory=list)


__all__ = [
    "PipelineStageStats",
    "PipelineTimingRun",
    "PipelineTimingSummaryOut",
    "PipelineTimingTotals",
]
