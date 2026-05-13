from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProjectPatch(BaseModel):
    """Partial update for a dossier (title rename, description edits)."""

    title: str | None = None
    description: str | None = None


class ProjectCreate(BaseModel):
    title: str = "Untitled"
    description: str
    intake_mode: Literal["IDEA", "MID_BUILD", "PRE_LAUNCH"] = "IDEA"
    landing_page_url: str | None = None
    mvp_feature_list: list[str] = Field(default_factory=list)
    existing_product_description: str | None = None
    dossier_axis: Literal["software", "hardware"] = "software"


class ProjectOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    status: str
    dossier_axis: str | None = None
    precis: str | None = None
    readings_json: str | None = None
    precis_title_fingerprint: str | None = None
    is_archived: bool = False
    brief_positioning: str | None = None
    brief_features_json: str | None = None
    brief_hook: str | None = None
    brief_completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectOut]
    total: int
