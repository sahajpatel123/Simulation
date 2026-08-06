"""
Pydantic schemas for the feature-prioritization read
``GET /api/v1/simulations/{id}/feature-prioritization``.

The endpoint answers the founder's "which features should I build or
polish first?" question from a completed run's per-cluster
``FeatureAdoptionArchitect`` metrics. It ranks the nine modeled feature
dimensions by *validated upside* (population-weighted adoption x unserved
headroom), tiers them ``BUILD_FIRST`` / ``GROW`` / ``WATCH`` /
``DEPRIORITIZE``, profiles clusters by feature depth, and maps the
founder's declared brief features onto the dimension with the strongest
keyword match.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VERDICT_READY: str = "READY"
VERDICT_FOCUSED: str = "FOCUSED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_READY, VERDICT_FOCUSED, VERDICT_INSUFFICIENT}
)

TIER_BUILD_FIRST: str = "BUILD_FIRST"
TIER_GROW: str = "GROW"
TIER_WATCH: str = "WATCH"
TIER_DEPRIORITIZE: str = "DEPRIORITIZE"
TIER_UNMAPPED: str = "UNMAPPED"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_BUILD_FIRST, TIER_GROW, TIER_WATCH, TIER_DEPRIORITIZE, TIER_UNMAPPED}
)

SEGMENT_ADVANCED: str = "ADVANCED"
SEGMENT_MAINSTREAM: str = "MAINSTREAM"
SEGMENT_LAGGING: str = "LAGGING"


class FeatureDimension(BaseModel):
    """One modeled feature dimension's market-level adoption read."""

    key: str
    label: str = ""
    adoption_rate: float = 0.0
    reach_weight: float = 0.0
    upside: float = 0.0
    priority_score: float = 0.0
    priority_tier: str = TIER_DEPRIORITIZE
    recommendation: str = ""


class BriefFeatureScore(BaseModel):
    """One founder-declared brief feature mapped onto a modeled dimension."""

    feature: str
    dimension_key: str | None = None
    dimension_label: str = ""
    adoption_rate: float | None = None
    priority_tier: str = TIER_UNMAPPED
    note: str = ""


class ClusterFeatureProfile(BaseModel):
    """One cluster's feature-adoption read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    feature_depth: float = 0.0
    core_dau_rate: float = 0.0
    power_discovery_rate: float = 0.0
    abandonment_rate: float = 0.0
    segment_tier: str = SEGMENT_LAGGING


class FeaturePrioritizationOut(BaseModel):
    """Full feature-prioritization read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    dimensions: list[FeatureDimension] = Field(default_factory=list)
    cluster_profiles: list[ClusterFeatureProfile] = Field(default_factory=list)
    brief_features: list[BriefFeatureScore] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BriefFeatureScore",
    "ClusterFeatureProfile",
    "FeatureDimension",
    "FeaturePrioritizationOut",
    "SEGMENT_ADVANCED",
    "SEGMENT_LAGGING",
    "SEGMENT_MAINSTREAM",
    "TIER_BUILD_FIRST",
    "TIER_DEPRIORITIZE",
    "TIER_GROW",
    "TIER_UNMAPPED",
    "TIER_WATCH",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_FOCUSED",
    "VERDICT_INSUFFICIENT",
    "VERDICT_READY",
]
