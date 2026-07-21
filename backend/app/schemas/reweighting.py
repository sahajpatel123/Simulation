"""
Pydantic schemas for the reweighting-preview endpoint
``GET /projects/{id}/reweighting-preview``.

The preview lets a founder see which cluster reweighting rule bundle the
simulation engine will apply for their project before they commit compute
to a full run. This is purely informational — no DB writes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClusterWeight(BaseModel):
    cluster_id: str
    cluster_name: str
    population_weight: float
    source: str = "registry"  # "registry" | "amplified" | "suppressed"


class ReweightingPreviewOut(BaseModel):
    project_id: int
    rule_bundle: str = ""
    product_type: str = ""
    aov: float | None = None
    geography: str | None = None
    segment: str | None = None
    age_target: str | None = None
    suppressed: list[str] = Field(default_factory=list)
    amplified: list[dict[str, Any]] = Field(default_factory=list)
    top_clusters: list[ClusterWeight] = Field(default_factory=list)
    bottom_clusters: list[ClusterWeight] = Field(default_factory=list)
    total_weight_sum: float = 1.0
    baseline_weight_sum: float = 1.0
    message: str = ""


__all__ = [
    "ClusterWeight",
    "ReweightingPreviewOut",
]
