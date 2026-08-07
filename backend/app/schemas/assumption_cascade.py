"""
Pydantic schemas for the assumption-cascade read
``GET /api/v1/simulations/{id}/assumption-cascade``.

The endpoint answers the founder's "which assumptions, if wrong, cascade
into failure?" question from a completed run's per-cluster
``AssumptionCascadeArchitect`` metrics. It computes a
population-weighted cascade risk index (0..1, higher = worse), tiers
every covered cluster ``LOW`` / ``ELEVATED`` / ``HIGH`` / ``CRITICAL``,
attributes each cluster's dominant blocker (existential cascade,
compound dual-assumption failure, validation blind spots, or sensitive
segments), and ranks the highest-risk clusters for validation focus.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_STABLE: str = "STABLE"
VERDICT_WATCH: str = "WATCH"
VERDICT_RISKY: str = "RISKY"
VERDICT_HIGH_RISK: str = "HIGH_RISK"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_STABLE,
        VERDICT_WATCH,
        VERDICT_RISKY,
        VERDICT_HIGH_RISK,
        VERDICT_INSUFFICIENT,
    }
)

TIER_LOW: str = "LOW"
TIER_ELEVATED: str = "ELEVATED"
TIER_HIGH: str = "HIGH"
TIER_CRITICAL: str = "CRITICAL"

VALID_TIERS: frozenset[str] = frozenset({TIER_LOW, TIER_ELEVATED, TIER_HIGH, TIER_CRITICAL})

BLOCKER_NONE: str = "none"
BLOCKER_EXISTENTIAL: str = "existential_risk"
BLOCKER_DUAL_FAILURE: str = "dual_failure_risk"
BLOCKER_BLIND_SPOT: str = "validation_blind_spot"
BLOCKER_SENSITIVE_SEGMENTS: str = "sensitive_segments"

VALID_BLOCKERS: frozenset[str] = frozenset(
    {
        BLOCKER_NONE,
        BLOCKER_EXISTENTIAL,
        BLOCKER_DUAL_FAILURE,
        BLOCKER_BLIND_SPOT,
        BLOCKER_SENSITIVE_SEGMENTS,
    }
)

BLOCKER_LABELS: dict[str, str] = {
    BLOCKER_NONE: "No dominant blocker",
    BLOCKER_EXISTENTIAL: "Existential assumption cascade risk",
    BLOCKER_DUAL_FAILURE: "Compound dual-assumption failure",
    BLOCKER_BLIND_SPOT: "Unvalidated assumption blind spots",
    BLOCKER_SENSITIVE_SEGMENTS: "High-sensitivity segments exposed",
}


class ClusterCascadeProfile(BaseModel):
    """One cluster's assumption-cascade risk read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    total_cascade_risk: float = 0.0
    compound_failure_probability: float = 0.0
    blind_spot_score: float = 0.0
    primary_failure_domain_delta: float = 0.0
    critical_assumption_count: float = 0.0
    validated_assumption_count: float = 0.0
    positive_cascade_active: bool = False
    cascade_tier: str = TIER_LOW
    blockers: list[str] = Field(default_factory=list)
    architect_flags: list[str] = Field(default_factory=list)


class AssumptionCascadeOut(BaseModel):
    """Full assumption-cascade read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    cascade_index: float = 0.0
    weighted_compound_failure_probability: float = 0.0
    weighted_blind_spot_score: float = 0.0
    weighted_primary_failure_domain_delta: float = 0.0
    weighted_critical_assumption_count: float = 0.0
    weighted_validated_assumption_count: float = 0.0
    positive_cascade_share: float = 0.0
    low_share: float = 0.0
    elevated_share: float = 0.0
    high_share: float = 0.0
    critical_share: float = 0.0
    primary_blocker: str = BLOCKER_NONE
    primary_blocker_label: str = "No dominant blocker"
    primary_blocker_share: float = 0.0
    blocker_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterCascadeProfile] = Field(default_factory=list)
    top_risk_clusters: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BLOCKER_BLIND_SPOT",
    "BLOCKER_DUAL_FAILURE",
    "BLOCKER_EXISTENTIAL",
    "BLOCKER_LABELS",
    "BLOCKER_NONE",
    "BLOCKER_SENSITIVE_SEGMENTS",
    "TIER_CRITICAL",
    "TIER_ELEVATED",
    "TIER_HIGH",
    "TIER_LOW",
    "VALID_BLOCKERS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_HIGH_RISK",
    "VERDICT_INSUFFICIENT",
    "VERDICT_RISKY",
    "VERDICT_STABLE",
    "VERDICT_WATCH",
    "AssumptionCascadeOut",
    "ClusterCascadeProfile",
]
