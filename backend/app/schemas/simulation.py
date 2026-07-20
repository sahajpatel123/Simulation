from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SimulationCreate(BaseModel):
    project_id: int
    consumer_volume: int = Field(default=10000, ge=100, le=100000)


class SimulationOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results_json: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationStatusOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    task_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationResultOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    cluster_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    domain_findings: list[Any] = Field(default_factory=list)
    primary_failure_domain: str = "unknown"
    highest_value_cluster: dict[str, Any] = Field(default_factory=dict)
    architect_accountability: dict[str, Any] = Field(default_factory=dict)
    product_type_detected: str = ""
    cluster_narrative: str = ""
    signal_quality: float | None = None
    user_blindspots: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RunTraceStageOut(BaseModel):
    """One stage entry in a simulation's run trace (elapsed_ms + items)."""

    name: str
    elapsed_ms: float
    items: int | None = None
    status: str = "ok"


class SimulationRunTraceOut(BaseModel):
    """Structured per-stage timing for a completed simulation.

    Stages: product_type_and_reweighting, architect_loop, domain_reports,
    accountability. The summary dict carries scalar counters
    (architect_calls, architect_failures, architect_skipped,
    clusters_processed). Use ``stages`` for waterfall UI and
    ``summary`` / ``total_ms`` for log-style inspection.
    """

    id: int
    project_id: int
    status: str
    total_ms: float | None = None
    stage_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    stages: list[RunTraceStageOut] = Field(default_factory=list)
    available: bool = False
    message: str = ""

    model_config = {"from_attributes": True}
