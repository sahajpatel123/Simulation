"""
Pydantic schemas for the market-sizing insight endpoint
``GET /api/v1/simulations/{id}/market-sizing``.

The endpoint turns a completed simulation's weighted
conversion into a TAM / SAM / SOM projection plus an
annual-revenue estimate, so founders can sanity-check
"is this idea big enough?" without leaving the dashboard.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarketSizingSignal(BaseModel):
    """One traffic-light signal for the market-sizing digest."""

    key: str = ""
    label: str = ""
    level: str = "watch"  # ok | watch | critical
    message: str = ""


class SegmentProjection(BaseModel):
    """One cluster's contribution to the obtainable market."""

    cluster_id: str = ""
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    som_share: float = 0.0  # share of projected SOM customers


class MarketSizingOut(BaseModel):
    """Full market-sizing projection for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    overall_conversion: float = 0.0
    total_agents: int = 0
    market_size: int = 0
    tam_customers: int = 0
    sam_customers: int = 0
    som_customers: int = 0
    reachable_fraction: float = 0.0
    average_order_value: float = 0.0
    purchase_frequency_per_year: float = 0.0
    annual_revenue: float = 0.0
    revenue_per_1000_visitors: float = 0.0
    product_type_detected: str = ""
    primary_failure_domain: str = "unknown"
    signal_quality: float | None = None
    top_segments: list[SegmentProjection] = Field(default_factory=list)
    signals: list[MarketSizingSignal] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "MarketSizingSignal",
    "SegmentProjection",
    "MarketSizingOut",
]
