"""
Pydantic schemas for the cultural-fit read
``GET /api/v1/simulations/{id}/cultural-fit``.

The endpoint answers the founder's "will this resonate culturally, and
which localization lever should I pull first?" question from a completed
run's per-cluster ``CulturalContextArchitect`` metrics. It computes a
population-weighted cultural-fit index (0..1, higher = better fit),
tiers every covered cluster ``STRONG`` / ``MODERATE`` / ``WEAK`` /
``MISALIGNED``, attributes each cluster's primary cultural barrier
(language, alignment, family gatekeeper, religious sensitivity,
seasonal timing, geography), and ranks localization levers by the share
of the covered market they touch. ``CulturalContextArchitect`` runs in
every conductor stack, so all product types are supported.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_STRONG_FIT: str = "STRONG_FIT"
VERDICT_MODERATE_FIT: str = "MODERATE_FIT"
VERDICT_WEAK_FIT: str = "WEAK_FIT"
VERDICT_MISALIGNED: str = "MISALIGNED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_STRONG_FIT,
        VERDICT_MODERATE_FIT,
        VERDICT_WEAK_FIT,
        VERDICT_MISALIGNED,
        VERDICT_INSUFFICIENT,
    }
)

TIER_STRONG: str = "STRONG"
TIER_MODERATE: str = "MODERATE"
TIER_WEAK: str = "WEAK"
TIER_MISALIGNED: str = "MISALIGNED"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_STRONG, TIER_MODERATE, TIER_WEAK, TIER_MISALIGNED}
)

# Ordered cultural-barrier keys. ``language_access`` is the fallback
# winner on ties so a generally-weak cultural read points at the most
# common, most actionable barrier (localization) rather than a
# secondary one.
BARRIER_LANGUAGE: str = "language_access"
BARRIER_ALIGNMENT: str = "cultural_alignment"
BARRIER_FAMILY: str = "family_gatekeeper"
BARRIER_RELIGIOUS: str = "religious_sensitivity"
BARRIER_SEASONAL: str = "seasonal_timing"
BARRIER_GEO: str = "geo_mismatch"

VALID_BARRIERS: frozenset[str] = frozenset(
    {
        BARRIER_LANGUAGE,
        BARRIER_ALIGNMENT,
        BARRIER_FAMILY,
        BARRIER_RELIGIOUS,
        BARRIER_SEASONAL,
        BARRIER_GEO,
    }
)

LEVER_LOCALIZATION: str = "localization"
LEVER_MESSAGING: str = "localized_messaging"
LEVER_FAMILY: str = "collective_purchase_design"
LEVER_COMPLIANCE: str = "cultural_compliance"
LEVER_SEASONAL: str = "seasonal_launch"
LEVER_GEO: str = "geo_go_to_market"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_LOCALIZATION,
        LEVER_MESSAGING,
        LEVER_FAMILY,
        LEVER_COMPLIANCE,
        LEVER_SEASONAL,
        LEVER_GEO,
    }
)


class ClusterCulturalProfile(BaseModel):
    """One cluster's cultural-fit read from CulturalContextArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    cultural_alignment_score: float = 0.0
    language_accessibility_score: float = 0.0
    family_influence_factor: float = 0.0
    seasonal_relevance_score: float = 0.0
    local_brand_trust: float = 0.0
    religious_sensitivity_risk: float = 0.0
    geo_target_alignment: float = 0.0
    overall_cultural_correction: float = 1.0
    cultural_fit_index: float = 0.0
    fit_tier: str = TIER_MISALIGNED
    primary_barrier: str = BARRIER_LANGUAGE
    primary_barrier_score: float = 0.0
    architect_flags: list[str] = Field(default_factory=list)


class CulturalLever(BaseModel):
    """One ranked localization lever and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class CulturalFitOut(BaseModel):
    """Full cultural-fit read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    fit_index: float = 0.0
    weighted_cultural_alignment: float = 0.0
    weighted_language_accessibility: float = 0.0
    weighted_family_influence: float = 0.0
    weighted_seasonal_relevance: float = 0.0
    weighted_local_brand_trust: float = 0.0
    weighted_religious_risk: float = 0.0
    weighted_geo_alignment: float = 0.0
    weighted_cultural_correction: float = 1.0
    strong_share: float = 0.0
    moderate_share: float = 0.0
    weak_share: float = 0.0
    misaligned_share: float = 0.0
    primary_barrier: str = BARRIER_LANGUAGE
    primary_barrier_label: str = "Language barrier"
    primary_barrier_share: float = 0.0
    barrier_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterCulturalProfile] = Field(
        default_factory=list
    )
    levers: list[CulturalLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BARRIER_ALIGNMENT",
    "BARRIER_FAMILY",
    "BARRIER_GEO",
    "BARRIER_LANGUAGE",
    "BARRIER_RELIGIOUS",
    "BARRIER_SEASONAL",
    "ClusterCulturalProfile",
    "CulturalFitOut",
    "CulturalLever",
    "LEVER_COMPLIANCE",
    "LEVER_FAMILY",
    "LEVER_GEO",
    "LEVER_LOCALIZATION",
    "LEVER_MESSAGING",
    "LEVER_SEASONAL",
    "TIER_MISALIGNED",
    "TIER_MODERATE",
    "TIER_STRONG",
    "TIER_WEAK",
    "VALID_BARRIERS",
    "VALID_LEVERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_INSUFFICIENT",
    "VERDICT_MISALIGNED",
    "VERDICT_MODERATE_FIT",
    "VERDICT_STRONG_FIT",
    "VERDICT_WEAK_FIT",
]
