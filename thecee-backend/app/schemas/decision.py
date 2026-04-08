from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ScenarioParameters(BaseModel):
    price_point: float | None = Field(default=None, ge=1.0)
    price_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    market_maturity: float | None = Field(default=None, ge=0.0, le=1.0)
    growth_rate_per_month: float | None = Field(default=None, ge=-50.0, le=200.0)
    consumer_volume: int | None = Field(default=None, ge=100)
    positioning: str | None = None
    go_to_market: str | None = None
    notes: str | None = None


class ScenarioIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    parameters: ScenarioParameters = Field(default_factory=ScenarioParameters)


class DecisionCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10, max_length=1000)
    scenarios: list[ScenarioIn] = Field(..., min_length=2, max_length=4)

    @field_validator("scenarios")
    @classmethod
    def unique_names(cls, value: list[ScenarioIn]) -> list[ScenarioIn]:
        names = [scenario.name for scenario in value]
        if len(names) != len(set(names)):
            raise ValueError("Each scenario must have a unique name")
        return value


class ScenarioResult(BaseModel):
    scenario_name: str
    scenario_description: str
    parameters_used: dict
    conversion_rate: float
    ci_low: float
    ci_high: float
    revenue_projection: float
    survival_probability: float
    confidence_score: int
    worst_drop_off_stage: str
    rank: int


class DecisionOut(BaseModel):
    id: int
    project_id: int
    title: str
    description: str
    status: str
    scenarios: list[ScenarioResult]
    recommended_scenario: str | None
    winner_margin: float
    key_insights: list[str]
    task_id: str | None
    generated_at: str | None
    message: str = "Decision comparison completed"


class DecisionStatusOut(BaseModel):
    id: int
    project_id: int
    title: str
    status: str
    task_id: str | None
    result: DecisionOut | None = None
