"""Schemas for the simulation-backed runway growth target."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwayGrowthTargetVerdict = Literal[
    "NO_GROWTH_REQUIRED",
    "PLAN_SUFFICIENT",
    "GROWTH_GAP",
    "INFEASIBLE",
]

RunwayGrowthConstraint = Literal[
    "NONE",
    "GROWTH_PLAN",
    "FIRST_MONTH_CASH",
    "UNIT_ECONOMICS",
    "HORIZON_OR_CASH",
]


class RunwayGrowthScenarioOut(BaseModel):
    """Cash-runway outcome for one monthly visitor-growth rate."""

    monthly_visitor_growth_rate: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwayGrowthTargetOut(BaseModel):
    """Minimum growth needed to reach break-even before cash runs out."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwayGrowthTargetVerdict = "INFEASIBLE"
    constraint: RunwayGrowthConstraint = "HORIZON_OR_CASH"
    weighted_conversion_rate: float = 0.0
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    cost_per_visitor: float = 0.0
    required_monthly_visitor_growth_rate: float | None = None
    growth_gap_percentage_points: float | None = None
    planned: RunwayGrowthScenarioOut
    target: RunwayGrowthScenarioOut | None = None
    maximum_tested: RunwayGrowthScenarioOut
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwayGrowthConstraint",
    "RunwayGrowthScenarioOut",
    "RunwayGrowthTargetOut",
    "RunwayGrowthTargetVerdict",
]
