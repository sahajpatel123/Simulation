"""Schemas for the simulation-backed runway acquisition-cost ceiling."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwayAcquisitionCeilingVerdict = Literal[
    "PLAN_WITHIN_CEILING",
    "PLAN_EXCEEDS_CEILING",
    "INFEASIBLE",
]

RunwayAcquisitionConstraint = Literal[
    "NONE",
    "ACQUISITION_COST_PLAN",
    "UNIT_ECONOMICS",
    "OPERATING_PLAN",
    "SEARCH_LIMIT",
]


class RunwayAcquisitionScenarioOut(BaseModel):
    """Cash-runway outcome for one blended cost per visitor."""

    cost_per_visitor: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwayAcquisitionCeilingOut(BaseModel):
    """Maximum acquisition cost per visitor that preserves runway."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwayAcquisitionCeilingVerdict = "INFEASIBLE"
    constraint: RunwayAcquisitionConstraint = "OPERATING_PLAN"
    weighted_conversion_rate: float = 0.0
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    planned_cost_per_visitor: float = 0.0
    cash_safe_cost_per_visitor_ceiling: float | None = None
    cost_per_visitor_headroom: float | None = None
    required_cost_per_visitor_reduction: float | None = None
    search_limit_reached: bool = False
    planned: RunwayAcquisitionScenarioOut
    ceiling: RunwayAcquisitionScenarioOut | None = None
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwayAcquisitionCeilingOut",
    "RunwayAcquisitionCeilingVerdict",
    "RunwayAcquisitionConstraint",
    "RunwayAcquisitionScenarioOut",
]
