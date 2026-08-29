"""Schemas for the simulation-backed runway spending ceiling."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwaySpendCeilingVerdict = Literal[
    "PLAN_WITHIN_CEILING",
    "PLAN_EXCEEDS_CEILING",
    "INFEASIBLE",
]

RunwaySpendCeilingConstraint = Literal[
    "NONE",
    "FIXED_COST_PLAN",
    "UNIT_ECONOMICS",
    "SEARCH_LIMIT",
]


class RunwaySpendScenarioOut(BaseModel):
    """Cash-runway outcome for one monthly fixed-cost budget."""

    monthly_fixed_costs: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwaySpendCeilingOut(BaseModel):
    """Maximum recurring fixed spend that preserves cash to break-even."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwaySpendCeilingVerdict = "INFEASIBLE"
    constraint: RunwaySpendCeilingConstraint = "UNIT_ECONOMICS"
    weighted_conversion_rate: float = 0.0
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    planned_monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    cost_per_visitor: float = 0.0
    cash_safe_monthly_fixed_cost_ceiling: float | None = None
    monthly_fixed_cost_headroom: float | None = None
    required_monthly_cost_reduction: float | None = None
    search_limit_reached: bool = False
    planned: RunwaySpendScenarioOut
    ceiling: RunwaySpendScenarioOut | None = None
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwaySpendCeilingConstraint",
    "RunwaySpendCeilingOut",
    "RunwaySpendCeilingVerdict",
    "RunwaySpendScenarioOut",
]
