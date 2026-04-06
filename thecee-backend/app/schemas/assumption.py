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
