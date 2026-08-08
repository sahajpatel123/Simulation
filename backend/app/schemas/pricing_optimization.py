"""
Pydantic schemas for the pricing-optimization read
``GET /api/v1/simulations/{id}/pricing-optimization``.

The endpoint answers the founder's "should I charge more or less?" question
from a completed run's per-cluster pricing metrics (price ceiling and
will-pay probability). It builds an AOV-relative demand curve, finds the
revenue-optimal price, estimates price elasticity around the current price,
and flags clusters that are priced above their willingness-to-pay ceiling.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

VERDICT_UNDERPRICED: str = "UNDERPRICED"
VERDICT_OVERPRICED: str = "OVERPRICED"
VERDICT_PRICE_OPTIMAL: str = "PRICE_OPTIMAL"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VALID_VERDICTS: frozenset[str] = frozenset({
    VERDICT_UNDERPRICED,
    VERDICT_OVERPRICED,
    VERDICT_PRICE_OPTIMAL,
    VERDICT_INSUFFICIENT,
})


class PricePoint(BaseModel):
    """One candidate price on the demand curve."""

    price: float = 0.0
    market_conversion: float = 0.0
    market_revenue: float = 0.0
    demand_retained_pct: float = 0.0


class ClusterPriceProfile(BaseModel):
    """One cluster's willingness-to-pay read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    price_ceiling: float = 0.0
    will_pay_probability: float = 0.0
    conversion_at_base_price: float = 0.0
    optimal_price: float = 0.0
    at_ceiling: bool = False
    ceiling_gap_pct: float = 0.0


class PricingOptimizationOut(BaseModel):
    """Full pricing-optimization read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    product_type: str = "saas"
    aov: float = 0.0
    base_price: float = 0.0
    base_market_conversion: float = 0.0
    base_market_revenue: float = 0.0
    revenue_optimal_price: float | None = None
    revenue_at_optimal: float = 0.0
    revenue_lift_vs_base_pct: float | None = None
    recommended_price: float | None = None
    overall_elasticity: float | None = None
    verdict: str = VERDICT_INSUFFICIENT
    price_points: list[PricePoint] = Field(default_factory=list)
    cluster_profiles: list[ClusterPriceProfile] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    key_signals: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VALID_VERDICTS",
    "VERDICT_UNDERPRICED",
    "VERDICT_OVERPRICED",
    "VERDICT_PRICE_OPTIMAL",
    "VERDICT_INSUFFICIENT",
    "PricePoint",
    "ClusterPriceProfile",
    "PricingOptimizationOut",
]
