from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = "Untitled"
    description: str
    intake_mode: Literal["IDEA", "MID_BUILD", "PRE_LAUNCH"] = "IDEA"
    landing_page_url: str | None = None
    mvp_feature_list: list[str] = Field(default_factory=list)
    existing_product_description: str | None = None


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
