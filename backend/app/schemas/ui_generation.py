from typing import Optional

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
    pages_detected: list[str]
    message: str = "UI generated successfully"
