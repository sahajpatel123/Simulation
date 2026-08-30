"""Schemas for the simulation-backed runway conversion target."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunwayConversionTargetVerdict = Literal[
    "PREDICTION_SUFFICIENT",
    "CONVERSION_GAP",
    "INFEASIBLE",
]

RunwayConversionConstraint = Literal[
    "NONE",
    "SIMULATED_CONVERSION",
    "FIRST_MONTH_CASH",
    "UNIT_ECONOMICS",
    "HORIZON_OR_CASH",
]


class RunwayConversionScenarioOut(BaseModel):
    """Cash-runway outcome for one visitor-to-purchase conversion rate."""

    conversion_rate: float = 0.0
    break_even_month: int | None = None
    cash_out_month: int | None = None
    lowest_cash_balance: float = 0.0
    ending_cash_balance: float = 0.0
    succeeds: bool = False


class RunwayConversionTargetOut(BaseModel):
    """Minimum conversion needed to reach break-even before cash runs out."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: RunwayConversionTargetVerdict = "INFEASIBLE"
    constraint: RunwayConversionConstraint = "HORIZON_OR_CASH"
    simulated_conversion_rate: float = 0.0
    required_conversion_rate: float | None = None
    conversion_gap_percentage_points: float | None = None
    conversion_headroom_percentage_points: float | None = None
    relative_conversion_lift_percent: float | None = None
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    gross_margin: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    cost_per_visitor: float = 0.0
    predicted: RunwayConversionScenarioOut
    target: RunwayConversionScenarioOut | None = None
    maximum_tested: RunwayConversionScenarioOut
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RunwayConversionConstraint",
    "RunwayConversionScenarioOut",
    "RunwayConversionTargetOut",
    "RunwayConversionTargetVerdict",
]
