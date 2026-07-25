from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectPatch(BaseModel):
    """Partial update for a dossier (title rename, description edits)."""

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)


class ProjectDuplicateIn(BaseModel):
    """Body for ``POST /projects/{id}/duplicate``."""

    new_title: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional override title. When omitted, the duplicate uses "
            '"<original> (copy)" / "(copy N)" naming.'
        ),
    )
    include_simulations: bool = Field(
        default=False,
        description=(
            "When true, snapshots of the source project's completed "
            "simulations are copied into the duplicate. Default false — "
            "duplicates are intentionally clean for A/B variants."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "When true, return the planned payload without writing to "
            "the DB. Useful for previewing the duplicate in the dashboard."
        ),
    )


class ProjectDuplicateOut(BaseModel):
    """Response from ``POST /projects/{id}/duplicate``."""

    model_config = ConfigDict(  # type: ignore[assignment]
        json_schema_extra={
            "example": {
                "project": {
                    "id": 99,
                    "title": "My Idea (copy)",
                    "status": "DRAFT",
                    "user_id": 7,
                },
                "source_project_id": 42,
                "simulations_copied": 0,
                "environment_copied": True,
                "dry_run": False,
            }
        }
    )

    project: ProjectOut
    source_project_id: int
    simulations_copied: int = 0
    environment_copied: bool = False
    dry_run: bool = False


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled", max_length=500)
    description: str = Field(..., max_length=5000)
    intake_mode: Literal["IDEA", "MID_BUILD", "PRE_LAUNCH"] = "IDEA"
    landing_page_url: str | None = Field(default=None, max_length=2048)
    # Cap both the list length AND each string item. ``Field(max_length=50)``
    # only constrains the list — without per-item caps a user could submit
    # 50 strings of 10MB each, which would then be concatenated into the
    # LLM prompt via "Shipped features: ..." in intake_processor.
    mvp_feature_list: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=50
    )
    existing_product_description: str | None = Field(default=None, max_length=5000)
    dossier_axis: Literal["software", "hardware"] = "software"


class BriefSave(BaseModel):
    """Body for POST /projects/{id}/brief.

    Replaces the prior ``payload: dict`` so Pydantic enforces types,
    length caps, and field presence — the prior contract accepted any
    JSON shape and let the handler reach for ``payload.get("...")``
    with no length cap, so a 10MB ``positioning`` string could be
    persisted to the DB on a single request.
    """

    positioning: str = Field(default="", max_length=2000)
    features: list[str] = Field(default_factory=list, max_length=5)
    hook: str = Field(default="", max_length=1000)
    mark_complete: bool = False


class BriefAssistRequest(BaseModel):
    """Body for POST /projects/{id}/brief/assist.

    Replaces the prior ``payload: dict``. ``mode`` and ``field`` are
    pinned to a known enum so the handler can't be tricked into
    dispatching to an arbitrary LLM mode.
    """

    mode: Literal["refine", "suggest", "critique"]
    field: Literal["positioning", "features", "hook"]
    current_value: str = Field(default="", max_length=2000)


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


# ProjectDuplicateOut references ProjectOut (defined above). Resolve the
# forward reference so Pydantic can build the nested model.
ProjectDuplicateOut.model_rebuild()


class ProjectListResponse(BaseModel):
    projects: list[ProjectOut]
    total: int
