"""Schemas for the simulation-backed runway price target."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwayPriceTargetVerdict = Literal[
    "PLAN_PRICE_SUFFICIENT",
    "PRICE_GAP",
    "INFEASIBLE",
]

RunwayPriceConstraint = Literal[
    "NONE",
    "PRICE_PLAN",
    "DEMAND_SIGNAL",
    "MARGIN_OR_FREQUENCY",
    "SUPPORTED_PRICE_LIMIT",
]


class RunwayPriceScenarioOut(BaseModel):
    """Cash-runway outcome for one average order value."""

    average_order_value: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwayPriceTargetOut(BaseModel):
    """Minimum average order value that preserves cash to break-even."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwayPriceTargetVerdict = "INFEASIBLE"
    constraint: RunwayPriceConstraint = "SUPPORTED_PRICE_LIMIT"
    weighted_conversion_rate: float = 0.0
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    monthly_fixed_costs: float = 0.0
    planned_average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    cost_per_visitor: float = 0.0
    required_average_order_value: float | None = None
    price_headroom: float | None = None
    required_price_increase: float | None = None
    relative_price_increase_percent: float | None = None
    planned: RunwayPriceScenarioOut
    target: RunwayPriceScenarioOut | None = None
    maximum_tested: RunwayPriceScenarioOut
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwayPriceConstraint",
    "RunwayPriceScenarioOut",
    "RunwayPriceTargetOut",
    "RunwayPriceTargetVerdict",
]
