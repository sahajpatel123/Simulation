from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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
