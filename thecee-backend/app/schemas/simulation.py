from datetime import datetime

from pydantic import BaseModel, Field


class SimulationCreate(BaseModel):
    project_id: int
    consumer_volume: int = Field(default=10000, ge=100, le=100000)


class SimulationOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results_json: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationStatusOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    task_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationResultOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
