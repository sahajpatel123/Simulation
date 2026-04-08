from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    description: str


class ProjectOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    status: str

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectOut]
    total: int
