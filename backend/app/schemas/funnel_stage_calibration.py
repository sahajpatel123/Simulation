"""Pydantic schemas for stage-level funnel calibration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FunnelStageCorrectionOut(BaseModel):
    """One learned per-stage pass-through correction row."""

    id: int
    product_type: str
    stage: str
    cluster_id: str = "ALL"
    from_state: str
    to_state: str
    correction_scalar: float = Field(default=1.0, ge=0.0)
    confidence_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    effective_sample_count: float = Field(default=0.0, ge=0.0)
    sample_count: int = Field(default=0, ge=0)
    mean_bias: float | None = None
    scope: str = ""
    last_updated: datetime | None = None

    model_config = {"from_attributes": True}


class FunnelStageCorrectionListOut(BaseModel):
    """Response from ``GET /calibration/funnel-stage``."""

    generated_at: datetime
    count: int = Field(default=0, ge=0)
    corrections: list[FunnelStageCorrectionOut] = Field(default_factory=list)


__all__ = [
    "FunnelStageCorrectionListOut",
    "FunnelStageCorrectionOut",
]
