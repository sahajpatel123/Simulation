"""
Pydantic schemas for the unit-economics endpoint
``GET /simulations/{id}/unit-economics``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


VALID_VERDICTS: frozenset[str] = frozenset(
    {"STRONG", "VIABLE", "MARGINAL", "UNPROFITABLE", "INSUFFICIENT_DATA"}
)


class ClusterUnitEconomics(BaseModel):
    """One cluster's per-customer economics read."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    demand_weight: float = 0.0
    effective_price: float = 0.0
    price_ceiling: float = 0.0
    will_pay_probability: float = 0.0
    monthly_contribution: float = 0.0
    average_lifetime_months: float = 0.0
    ltv: float = 0.0
    cac: float = 0.0
    cac_multiplier: float = 1.0
    primary_channel: str = ""
    ltv_cac_ratio: float = 0.0
    payback_months: float | None = None
    affordable_cac: float = 0.0
    verdict: str = "INSUFFICIENT_DATA"


class CacScenario(BaseModel):
    """LTV:CAC read when blended acquisition cost is scaled by a factor."""

    label: str
    cac_multiplier: float = 1.0
    blended_cac: float = 0.0
    blended_ltv_cac_ratio: float = 0.0


class PriceScenario(BaseModel):
    """Per-customer economics if price moves, holding retention/volume constant."""

    label: str
    price_multiplier: float = 1.0
    blended_price: float = 0.0
    blended_ltv: float = 0.0
    blended_ltv_cac_ratio: float = 0.0
    capped_share: float = 0.0


class UnitEconomicsOut(BaseModel):
    """Full unit-economics read for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    signal_quality: float | None = None
    product_type: str = "saas"
    aov: float = 0.0
    gross_margin: float = 0.6
    purchase_frequency_per_year: float = 12.0
    base_cac: float = 0.0
    effective_base_cac: float = 0.0
    blended_price: float = 0.0
    blended_monthly_contribution: float = 0.0
    blended_lifetime_months: float = 0.0
    blended_ltv: float = 0.0
    blended_cac: float = 0.0
    blended_ltv_cac_ratio: float = 0.0
    blended_payback_months: float | None = None
    affordable_cac_ceiling: float = 0.0
    verdict: str = "INSUFFICIENT_DATA"
    strong_share: float = 0.0
    profitable_share: float = 0.0
    unprofitable_share: float = 0.0
    at_ceiling_share: float = 0.0
    best_cluster_id: str | None = None
    best_cluster_name: str = ""
    worst_cluster_id: str | None = None
    worst_cluster_name: str = ""
    total_clusters: int = 0
    clusters_with_data: int = 0
    recommendations: list[str] = Field(default_factory=list)
    cac_scenarios: list[CacScenario] = Field(default_factory=list)
    price_scenarios: list[PriceScenario] = Field(default_factory=list)
    cluster_profiles: list[ClusterUnitEconomics] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VALID_VERDICTS",
    "ClusterUnitEconomics",
    "CacScenario",
    "PriceScenario",
    "UnitEconomicsOut",
]
