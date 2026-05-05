from pydantic import BaseModel


class AssumptionExtractRequest(BaseModel):
    description: str | None = None


class AssumptionOut(BaseModel):
    id: int
    text: str
    category: str | None
    sensitivity: str
    impact_score: float
    is_hidden: bool

    model_config = {"from_attributes": True}


class AssumptionListResponse(BaseModel):
    project_id: int
    assumptions: list[AssumptionOut]
    total: int
    hidden_count: int
    message: str = "Assumptions extracted successfully"
    signal_quality: float | None = None
    signal_quality_tier: str | None = None
    claim_confidence_distribution: dict | None = None
    soft_contradiction_flags: list[str] = []
