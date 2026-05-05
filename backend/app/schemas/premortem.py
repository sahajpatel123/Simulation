from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FailureMode(BaseModel):
    title: str
    probability: float = Field(..., ge=0.05, le=0.95)
    severity: str
    trigger_condition: str
    linked_assumption_texts: list[str]
    intervention: str
    intervention_impact: str
    earliest_signal: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        valid = {"CRITICAL", "HIGH", "MEDIUM"}
        v = value.upper().strip()
        if v not in valid:
            return "MEDIUM"
        return v

    @field_validator("probability")
    @classmethod
    def clamp_probability(cls, value: float) -> float:
        return round(max(0.05, min(0.95, value)), 3)


class PremortemOut(BaseModel):
    project_id: int
    failure_modes: list[FailureMode]
    total: int
    critical_count: int
    generated_at: str
    message: str = "Pre-mortem analysis completed"


class PremortemRequest(BaseModel):
    description_override: str | None = None

