from typing import Any, Optional

from pydantic import BaseModel


class UIGenerateRequest(BaseModel):
    prompt: str
    product_type: str = "saas"
    pages_required: list[str] = ["home", "product", "checkout"]
    target_demographic: Optional[str] = None
    price_point: Optional[str] = None


class UIRefineRequest(BaseModel):
    generated_ui_id: int
    refinement_prompt: str


class GeneratedUIResponse(BaseModel):
    id: int
    project_id: int
    version: int
    html_preview_url: str
    html_content: str
    pages_detected: list[str]
    message: str = "UI generated successfully"


class UIVersionRow(BaseModel):
    id: int
    version: int
    product_type: str | None = None
    prompt: str | None = None
    html_preview_url: str
    created_at: str | None = None


class UIVersionHistoryResponse(BaseModel):
    uis: list[UIVersionRow]


class UIDiffEntry(BaseModel):
    selector: str = ""
    action: str = ""
    from_: str = ""
    to: str = ""

    model_config = {"populate_by_name": True}


class UIDiffResponse(BaseModel):
    from_version: int
    to_version: int
    changes: list[UIDiffEntry] = []


class UIRollbackResponse(BaseModel):
    id: int
    version: int
    html_preview_url: str
    message: str
