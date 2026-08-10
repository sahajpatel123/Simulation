from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FounderOutcomeSubmit(BaseModel):
    """Body for the lightweight founder-outcome POST.

    Replaces the prior ``body: dict`` on
    ``POST /calibration/outcome`` and ``POST /analytics/founder-outcome``
    so Pydantic enforces types, ranges, and length caps. The full
    structured outcome (with MRR / CAC / churn / DAU / NPS) is the
    separate ``OutcomeCreate`` used by ``POST /projects/{id}/outcomes``.

    ``actual_conversion_rate`` is constrained to ``[0.0, 1.0]`` so a
    hostile client cannot inject NaN, infinity, or negative values
    that would corrupt the calibration EMA. ``days_since_launch`` is
    bounded to ``[1, 3650]`` (10 years) and ``notes`` to 500 chars.
    """

    model_config = {"extra": "forbid"}

    simulation_id: int = Field(..., ge=1)
    actual_conversion_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    launched: bool = True
    days_since_launch: int = Field(default=30, ge=1, le=3650)
    notes: str | None = Field(default=None, max_length=500)


class OutcomeFeedbackRequest(BaseModel):
    """Body for POST /projects/{id}/outcome-feedback (full calibration flow).

    Replaces the prior ``body: dict`` with manual validation. Every
    numeric is range-checked, every text field is length-capped, and
    unknown keys are rejected via ``extra="forbid"``.
    """

    model_config = {"extra": "forbid"}

    simulation_id: int = Field(..., ge=1)
    actual_conversion_rate: float = Field(..., ge=0.0, le=1.0)
    days_since_launch: int = Field(default=90, ge=1, le=3650)
    data_confidence: Literal["EXACT", "ESTIMATED", "ROUGH"] = "ESTIMATED"
    product_changed_since_sim: bool = False
    pricing_changed: bool = False
    target_market_changed: bool = False
    actual_drop_at_browse_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    actual_drop_at_consider_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    actual_drop_at_decide_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_failure_reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class OutcomeCreate(BaseModel):
    actual_conversion_rate: float = Field(..., ge=0.0, le=1.0)
    actual_mrr: float = Field(..., ge=0.0)
    actual_cac: float = Field(..., ge=0.0)
    actual_churn_rate: float = Field(..., ge=0.0, le=1.0)
    days_since_launch: int = Field(default=30, ge=1, le=3650)
    actual_dau: float | None = Field(default=None, ge=0.0)
    actual_nps: float | None = Field(default=None, ge=-100.0, le=100.0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("actual_conversion_rate", "actual_churn_rate")
    @classmethod
    def reasonable_rate(cls, value: float) -> float:
        return round(value, 6)


class OutcomeBatchItem(OutcomeCreate):
    """One row in ``POST /projects/{id}/outcomes/batch``.

    Extends :class:`OutcomeCreate` with an optional ``simulation_id`` so a
    backfill row can bind to the simulation that was live when the real
    numbers were measured. When omitted, the endpoint uses the project's
    latest completed simulation (the same default as the single-record
    endpoint), which keeps the two routes' semantics consistent.
    """

    model_config = {"extra": "forbid"}

    simulation_id: int | None = Field(default=None, ge=1)


class OutcomeBatchCreate(BaseModel):
    """Body for ``POST /projects/{id}/outcomes/batch``.

    ``outcomes`` is capped at 100 rows so a single request cannot grow the
    outcomes table unboundedly; founders backfilling more history should
    paginate their upload in chunks. The endpoint is all-or-nothing: every
    row must validate, otherwise nothing is written.
    """

    model_config = {"extra": "forbid"}

    outcomes: list[OutcomeBatchItem] = Field(..., min_length=1, max_length=100)


class OutcomeBatchOut(BaseModel):
    """Response from ``POST /projects/{id}/outcomes/batch``.

    Echoes the hydrated records so the client can render calibration
    variance immediately without a follow-up history GET.
    """

    project_id: int
    created_count: int = Field(..., ge=0)
    outcomes: list[OutcomeRecord] = Field(default_factory=list)


class VarianceReport(BaseModel):
    conversion: float | None
    mrr: float | None
    cac: float | None
    churn: float | None

    def direction_label(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        if abs(value) < 5.0:
            return "ACCURATE"
        return "UNDER_ESTIMATED" if value > 0 else "OVER_ESTIMATED"


class OutcomeRecord(BaseModel):
    id: int
    project_id: int
    actual_conversion_rate: float
    actual_mrr: float
    actual_cac: float
    actual_churn_rate: float
    days_since_launch: int
    actual_dau: float | None
    actual_nps: float | None
    notes: str | None
    predicted_conversion_rate: float | None
    predicted_mrr: float | None
    simulation_id: int | None
    variance: VarianceReport
    calibration_score: float
    recorded_at: datetime

    model_config = {"from_attributes": True}


class OutcomeHistoryOut(BaseModel):
    project_id: int
    outcomes: list[OutcomeRecord]
    total: int = Field(
        default=0,
        ge=0,
        description="Total matching outcomes before pagination.",
    )
    filtered_total: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    has_more: bool = False
    average_calibration_score: float
    best_calibration_score: float
    worst_calibration_score: float
    calibration_trend: str
    message: str = "Outcome history retrieved"


class OutcomesDigestOut(BaseModel):
    """Response from ``GET /projects/{id}/outcomes-digest``.

    Single-payload digest of how accurate the project's
    predictions have been — composes the
    architect-leaderboard and calibration-health outputs
    into "how trustable are my numbers?" so the dashboard
    can render a one-tile calibration view without fanning
    out to /portfolio-summary + /calibration-health +
    /architect-leaderboard.

    * ``outcome_count`` — total outcomes recorded (incl.
      rows without both predicted + actual values).
    * ``usable_count`` — count of outcomes with both
      predicted + actual values (the only ones that
      contribute to MAE / bias / trend).
    * ``mean_abs_variance`` — population MAE across the
      usable rows (None when unusable).
    * ``bias_direction`` — ``OVER-PREDICTING`` /
      ``UNDER-PREDICTING`` / ``BALANCED`` /
      ``INSUFFICIENT_DATA``.
    * ``accuracy_trend`` — ``IMPROVING`` / ``STABLE`` /
      ``DEGRADING`` / ``INSUFFICIENT_DATA`` based on the
      recent-MAE vs prior-MAE delta.
    * ``best_architect`` / ``worst_architect`` — leaderboard
      entries flagged TRUSTED / TIGHTEN. ``None`` when no
      architect qualifies.
    * ``calibration_health`` — pass-through output of
      :func:`build_calibration_health` (or ``None``).
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    outcome_count: int = 0
    usable_count: int = 0
    mean_abs_variance: float | None = None
    bias_direction: str = "INSUFFICIENT_DATA"
    accuracy_trend: str = "INSUFFICIENT_DATA"
    best_architect: dict | None = None
    worst_architect: dict | None = None
    calibration_health: dict | None = None
    narrative: str = ""
    key_signals: list[dict] = []


OutcomeDigestOut = OutcomesDigestOut
