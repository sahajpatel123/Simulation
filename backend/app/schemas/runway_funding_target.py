"""Schemas for the simulation-backed runway funding target."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwayFundingTargetVerdict = Literal[
    "PLAN_FUNDED",
    "FUNDING_GAP",
    "INFEASIBLE",
]

RunwayFundingConstraint = Literal[
    "NONE",
    "STARTING_CASH",
    "UNIT_ECONOMICS",
    "BREAK_EVEN_HORIZON",
]


class RunwayFundingScenarioOut(BaseModel):
    """Cash-runway outcome for one opening-cash amount."""

    starting_cash: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwayFundingTargetOut(BaseModel):
    """Minimum opening cash needed to preserve runway to break-even."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwayFundingTargetVerdict = "INFEASIBLE"
    constraint: RunwayFundingConstraint = "BREAK_EVEN_HORIZON"
    weighted_conversion_rate: float = 0.0
    planned_starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    cost_per_visitor: float = 0.0
    minimum_starting_cash: float | None = None
    additional_cash_required: float | None = None
    funding_surplus: float | None = None
    planned: RunwayFundingScenarioOut
    target: RunwayFundingScenarioOut | None = None
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwayFundingConstraint",
    "RunwayFundingScenarioOut",
    "RunwayFundingTargetOut",
    "RunwayFundingTargetVerdict",
]
