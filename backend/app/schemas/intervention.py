from pydantic import BaseModel, Field, field_validator


class Intervention(BaseModel):
    id: str
    title: str
    description: str
    expected_impact: str
    difficulty: str
    estimated_cost: str
    linked_assumption: str | None = None
    linked_failure_mode: str | None = None
    priority_score: float = Field(..., ge=0.0, le=1.0)
    time_to_implement: str
    success_metric: str

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        valid = {"LOW", "MEDIUM", "HIGH"}
        normalized = value.upper().strip()
        return normalized if normalized in valid else "MEDIUM"

    @field_validator("priority_score")
    @classmethod
    def round_score(cls, value: float) -> float:
        return round(max(0.0, min(1.0, value)), 3)


class InterventionOut(BaseModel):
    project_id: int
    interventions: list[Intervention]
    total: int
    quick_wins: list[Intervention]
    generated_at: str
    context_used: dict[str, bool]
    message: str = "Interventions generated successfully"


class InterventionRequest(BaseModel):
    description_override: str | None = None
    max_interventions: int = Field(default=10, ge=3, le=20)
