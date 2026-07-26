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


class FindingsAggregateOut(BaseModel):
    """Response from ``GET /simulations/aggregate/findings``.

    Portfolio view of domain findings across N simulations:

    * ``total_findings`` — every finding across every sim in the batch.
    * ``filtered_findings`` — count of findings at or above the
      ``min_severity`` filter.
    * ``severity_breakdown`` — ``{CRITICAL/WARNING/INFO: count}``
      across *all* findings, ignoring the filter.
    * ``by_architect`` — per-architect rollup, sorted by
      ``finding_count DESC, critical_count DESC, name ASC``.
    * ``by_cluster`` — per-cluster rollup (which user segments are
      most affected), sorted by ``finding_count DESC, critical DESC,
      cluster_id ASC``.
    * ``top_architects`` — first ``top_n`` architect names (sorted).
    * ``top_findings`` — first ``top_n`` findings by conversion_impact
      DESC (tiebreaker: severity DESC, then architect + cluster).
    * ``architect_filter`` — echoed back (whitespace-stripped, but
      *not* casefolded — the UI can show the caller's original input).
    """

    total_findings: int = 0
    filtered_findings: int = 0
    severity_breakdown: dict[str, int] = {}
    by_architect: list[dict] = []
    by_cluster: list[dict] = []
    top_architects: list[str] = []
    top_findings: list[dict] = []
    simulation_count: int = 0
    simulations_with_findings: int = 0
    shared_domain_count: int = 0
    architect_filter: str | None = None


class OutcomesDigestOut(BaseModel):
    """Response from ``GET /simulations/aggregate/outcomes``.

    Portfolio view of predicted-vs-actual conversion accuracy across
    N simulations that have founder-recorded outcomes attached — the
    "calibration at scale" view. Each Outcome row contributes one
    ``(predicted, actual)`` pair (we keep the latest outcome per
    simulation id).

    * ``mae`` — Mean Absolute Error of the conversion rate (|predicted
      − actual|). Higher = less calibrated.
    * ``mape`` — Mean Absolute Percentage Error. Pairs where
      actual == 0 are excluded so the aggregate doesn't blow up.
    * ``rmse`` — Root Mean Squared Error (penalises outliers).
    * ``mae_count`` / ``mape_count`` — pair counts fed into each
      metric (often differ — MAPE drops zero-actuals).
    * ``outlier_count`` — pairs with |variance| above the (clamped)
      ``outlier_threshold`` query param. Default 0.10 (10pp).
    * ``direction_breakdown`` — ``{over, under, exact}`` histogram so
      the UI can render "we over-predicted 6 / under-predicted 2".
    * ``per_pair`` — raw (predicted, actual, variance, is_outlier)
      tuples for scatter plots.
    * ``simulation_count`` — total pairs in the input (incl. ones
      with no predicted value).
    * ``with_predictions`` — how many pairs had a non-null predicted
      value (the numerator of MAE / MAPE / RMSE).
    """

    mae: float = 0.0
    mape: float = 0.0
    rmse: float = 0.0
    mae_count: int = 0
    mape_count: int = 0
    outlier_count: int = 0
    direction_breakdown: dict[str, int] = {
        "over": 0,
        "under": 0,
        "exact": 0,
    }
    per_pair: list[dict] = []
    simulation_count: int = 0
    with_predictions: int = 0


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
