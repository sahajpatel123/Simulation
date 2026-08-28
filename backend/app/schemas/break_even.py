"""Pydantic schemas for the simulation break-even insight."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BreakEvenVerdict = Literal[
    "PROFITABLE",
    "NEAR_BREAK_EVEN",
    "SHORTFALL",
    "UNREACHABLE",
]


class BreakEvenOut(BaseModel):
    """Founder-facing monthly break-even projection for one simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: BreakEvenVerdict = "UNREACHABLE"
    weighted_conversion_rate: float = 0.0
    monthly_visitors: int = 0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    gross_margin: float = 0.0
    cost_per_visitor: float = 0.0
    monthly_customers: float = 0.0
    monthly_revenue: float = 0.0
    monthly_gross_profit: float = 0.0
    monthly_acquisition_cost: float = 0.0
    monthly_contribution: float = 0.0
    monthly_operating_result: float = 0.0
    contribution_per_customer: float = 0.0
    contribution_per_visitor: float = 0.0
    break_even_customers: int | None = None
    break_even_visitors: int | None = None
    additional_customers_needed: int | None = None
    additional_visitors_needed: int | None = None
    safety_margin_ratio: float | None = None
    maximum_affordable_cost_per_visitor: float = 0.0
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = ["BreakEvenOut", "BreakEvenVerdict"]
