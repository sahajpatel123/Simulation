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


class SimulationBatchStatusOut(BaseModel):
    """Response from ``GET /simulations/batch``.

    ``items`` is the ordered list of simulations the caller owns
    that matched the requested ids. ``not_found`` lists the ids
    that were either non-existent or owned by a different user —
    we never 404 the whole batch just because one id is bad.

    ``status_counts`` is a ``{status: count}`` summary of the
    returned items, so dashboard widgets can render "5 running, 12
    completed" without re-iterating the list. ``filtered_by_since``
    is the timestamp actually applied (echoed back so the UI can
    pin it for the next incremental poll).
    """

    items: list[SimulationStatusOut]
    not_found: list[int]
    requested: int
    status_counts: dict[str, int] = {}
    filtered_by_since: datetime | None = None


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
