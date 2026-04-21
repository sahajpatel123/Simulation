from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


VALID_PRODUCT_TYPES = frozenset(
    {
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
    }
)


class HardwareGenerateSpecRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1, max_length=200)
    product_type: str = Field(..., min_length=1, max_length=50)
    target_price_inr: float = Field(..., gt=0)
    material_preference: str | None = Field(None, max_length=10_000)
    dimensions_rough: dict[str, Any] | str | None = None


class HardwareRenderHintsOut(BaseModel):
    primary_shape: str
    dominant_material: str
    color_hex: str
    highlight_zones: list[str]


class HardwareGenerateSpecResponse(BaseModel):
    id: int
    spec_preview: str
    components: list[dict[str, Any]]
    stress_points: list[dict[str, Any]]
    render_hints: HardwareRenderHintsOut


class HardwareRefineSpecRequest(BaseModel):
    hardware_product_id: int = Field(..., ge=1)
    refinement_prompt: str = Field(..., min_length=1, max_length=20_000)


class HardwareRefineSpecResponse(BaseModel):
    hardware_product_id: int
    model_id: int
    spec: dict[str, Any]


class HardwareProductListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str | None
    product_type: str
    target_price_inr: float | None
    created_at: datetime


class HardwareProductDetailResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None
    category: str | None
    product_type: str
    target_price_inr: float | None
    material_spec: str | None
    dimensions_json: dict[str, Any] | None
    weight_grams: float | None
    created_at: datetime
    spec: dict[str, Any]
    render_hints: HardwareRenderHintsOut
