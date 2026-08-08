"""
Pydantic schemas for the after-sales lifecycle read
``GET /api/v1/simulations/{id}/after-sales``.

The endpoint answers the founder's "what happens after the purchase?"
question from a completed run's per-cluster
``AftersalesLifecycleArchitect`` metrics. It computes a
population-weighted after-sales index (0..1, higher = healthier) from
30-day support contact, repeat-purchase brand loyalty, warranty claim
likelihood, negative-review risk, spare-parts concern, expected product
lifespan and accessory attach, tiers every covered cluster ``STRONG`` /
``OK`` / ``FRAGILE`` / ``AT_RISK``, attributes each cluster's primary
after-sales risk, and ranks post-purchase levers by the share of the
covered market they touch.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_STRAINED: str = "STRAINED"
VERDICT_AT_RISK: str = "AT_RISK"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_HEALTHY,
        VERDICT_WATCH,
        VERDICT_STRAINED,
        VERDICT_AT_RISK,
        VERDICT_INSUFFICIENT,
    }
)

TIER_STRONG: str = "STRONG"
TIER_OK: str = "OK"
TIER_FRAGILE: str = "FRAGILE"
TIER_AT_RISK: str = "AT_RISK"

VALID_TIERS: frozenset[str] = frozenset(
    {TIER_STRONG, TIER_OK, TIER_FRAGILE, TIER_AT_RISK}
)

# Ordered after-sales risk keys. ``support_burden`` is the fallback
# winner on ties so a generally-strained read points at the most
# directly actionable operational risk first.
RISK_SUPPORT_BURDEN: str = "support_burden"
RISK_LOYALTY_GAP: str = "loyalty_gap"
RISK_WARRANTY_CLAIMS: str = "warranty_claims"
RISK_REVIEW: str = "review_risk"
RISK_SPARE_PARTS: str = "spare_parts"
RISK_LIFESPAN: str = "lifespan_risk"

VALID_RISKS: frozenset[str] = frozenset(
    {
        RISK_SUPPORT_BURDEN,
        RISK_LOYALTY_GAP,
        RISK_WARRANTY_CLAIMS,
        RISK_REVIEW,
        RISK_SPARE_PARTS,
        RISK_LIFESPAN,
    }
)

LEVER_SUPPORT_SELF_SERVICE: str = "support_self_service"
LEVER_EXTENDED_WARRANTY: str = "extended_warranty"
LEVER_LOYALTY_PROGRAM: str = "loyalty_program"
LEVER_ACCESSORY_BUNDLES: str = "accessory_bundles"
LEVER_REFURBISHMENT_PROGRAM: str = "refurbishment_program"
LEVER_REVIEW_RESPONSE: str = "review_response"
LEVER_SPARE_PARTS: str = "spare_parts"
LEVER_SUSTAINABILITY_COMMS: str = "sustainability_comms"
LEVER_LIFESPAN_ROADMAP: str = "lifespan_roadmap"

VALID_LEVERS: frozenset[str] = frozenset(
    {
        LEVER_SUPPORT_SELF_SERVICE,
        LEVER_EXTENDED_WARRANTY,
        LEVER_LOYALTY_PROGRAM,
        LEVER_ACCESSORY_BUNDLES,
        LEVER_REFURBISHMENT_PROGRAM,
        LEVER_REVIEW_RESPONSE,
        LEVER_SPARE_PARTS,
        LEVER_SUSTAINABILITY_COMMS,
        LEVER_LIFESPAN_ROADMAP,
    }
)

# Product types whose conductor stack includes
# AftersalesLifecycleArchitect.
SUPPORTED_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
    }
)


class ClusterAfterSalesProfile(BaseModel):
    """One cluster's after-sales read from AftersalesLifecycleArchitect."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    warranty_claim_likelihood: float = 0.0
    repair_vs_replace_threshold: float = 0.0
    support_contact_rate_30d: float = 0.0
    accessory_attach_rate: float = 0.0
    refurbished_participation: float = 0.0
    sustainability_concern: float = 0.0
    brand_loyalty_next_purchase: float = 0.0
    review_writing_likelihood: float = 0.0
    spare_parts_concern: float = 0.0
    expected_product_lifespan_y: float = 0.0
    after_sales_index: float = 0.0
    after_sales_tier: str = TIER_AT_RISK
    primary_risk: str = RISK_SUPPORT_BURDEN
    primary_risk_score: float = 0.0
    architect_flags: list[str] = Field(default_factory=list)


class AfterSalesLever(BaseModel):
    """One ranked post-purchase lever and the market it touches."""

    key: str
    label: str = ""
    market_value: float = 0.0
    opportunity_share: float = 0.0
    action: str = ""


class AfterSalesOut(BaseModel):
    """Full after-sales lifecycle read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    verdict: str = VERDICT_INSUFFICIENT
    after_sales_index: float = 0.0
    weighted_warranty_claim_likelihood: float = 0.0
    weighted_repair_vs_replace_threshold: float = 0.0
    weighted_support_contact_rate_30d: float = 0.0
    weighted_accessory_attach_rate: float = 0.0
    weighted_refurbished_participation: float = 0.0
    weighted_sustainability_concern: float = 0.0
    weighted_brand_loyalty_next_purchase: float = 0.0
    weighted_review_writing_likelihood: float = 0.0
    weighted_spare_parts_concern: float = 0.0
    weighted_expected_product_lifespan_y: float = 0.0
    strong_share: float = 0.0
    ok_share: float = 0.0
    fragile_share: float = 0.0
    at_risk_share: float = 0.0
    primary_risk: str = RISK_SUPPORT_BURDEN
    primary_risk_label: str = "High 30-day support contact"
    primary_risk_share: float = 0.0
    risk_distribution: dict[str, float] = Field(default_factory=dict)
    cluster_profiles: list[ClusterAfterSalesProfile] = Field(
        default_factory=list
    )
    levers: list[AfterSalesLever] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AfterSalesLever",
    "AfterSalesOut",
    "ClusterAfterSalesProfile",
    "LEVER_ACCESSORY_BUNDLES",
    "LEVER_EXTENDED_WARRANTY",
    "LEVER_LIFESPAN_ROADMAP",
    "LEVER_LOYALTY_PROGRAM",
    "LEVER_REFURBISHMENT_PROGRAM",
    "LEVER_REVIEW_RESPONSE",
    "LEVER_SPARE_PARTS",
    "LEVER_SUPPORT_SELF_SERVICE",
    "LEVER_SUSTAINABILITY_COMMS",
    "RISK_LIFESPAN",
    "RISK_LOYALTY_GAP",
    "RISK_REVIEW",
    "RISK_SPARE_PARTS",
    "RISK_SUPPORT_BURDEN",
    "RISK_WARRANTY_CLAIMS",
    "SUPPORTED_PRODUCT_TYPES",
    "TIER_AT_RISK",
    "TIER_FRAGILE",
    "TIER_OK",
    "TIER_STRONG",
    "VALID_LEVERS",
    "VALID_RISKS",
    "VALID_TIERS",
    "VALID_VERDICTS",
    "VERDICT_AT_RISK",
    "VERDICT_HEALTHY",
    "VERDICT_INSUFFICIENT",
    "VERDICT_STRAINED",
    "VERDICT_WATCH",
]
