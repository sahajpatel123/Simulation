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
    total: int
    average_calibration_score: float
    best_calibration_score: float
    worst_calibration_score: float
    calibration_trend: str
    message: str = "Outcome history retrieved"
