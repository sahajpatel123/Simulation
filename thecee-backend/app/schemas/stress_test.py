from pydantic import BaseModel


class AssumptionStressResult(BaseModel):
    assumption_id: int
    assumption_text: str
    sensitivity: str
    baseline_conversion: float
    stressed_conversion: float
    delta: float
    delta_pct: float
    kill_shot: bool
    kill_shot_prob: float
    recommendation: str


class StressTestOut(BaseModel):
    project_id: int
    status: str
    sensitivity_matrix: list[AssumptionStressResult]
    kill_shots: list[AssumptionStressResult]
    overall_risk_level: str
    baseline_conversion: float
    assumptions_tested: int
    generated_at: str
    message: str = "Stress test completed"


class StressTestStatusOut(BaseModel):
    project_id: int
    status: str
    task_id: str | None
    result: StressTestOut | None = None
