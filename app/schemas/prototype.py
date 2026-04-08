from pydantic import BaseModel, field_validator


class FunnelNode(BaseModel):
    id: str
    label: str
    stage: str
    expected_time_seconds: int | None = None

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, v: str) -> str:
        valid = {"ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE", "ABANDON"}
        v = v.upper()
        if v not in valid:
            raise ValueError(f"Stage must be one of {valid}")
        return v


class FunnelEdge(BaseModel):
    from_node: str
    to_node: str
    probability: float
    label: str | None = None

    @field_validator("probability")
    @classmethod
    def clamp_probability(cls, v: float) -> float:
        return min(1.0, max(0.0, v))


class FunnelGraph(BaseModel):
    nodes: list[FunnelNode]
    edges: list[FunnelEdge]


class PrototypeOut(BaseModel):
    id: int
    project_id: int
    html_content: str | None
    funnel_graph: FunnelGraph | None
    message: str = "Prototype generated successfully"

    model_config = {"from_attributes": True}
