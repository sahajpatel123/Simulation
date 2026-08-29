"""Pydantic schemas for the simulation-backed cash-runway forecast."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CashRunwayVerdict = Literal[
    "SELF_SUSTAINING",
    "FUNDED_TO_BREAK_EVEN",
    "CASH_GAP",
    "BEYOND_HORIZON",
    "INVIABLE",
]


class CashRunwayMonthOut(BaseModel):
    """One month in the cash-runway projection."""

    month: int
    monthly_visitors: int
    monthly_customers: float
    monthly_revenue: float
    monthly_operating_result: float
    ending_cash_balance: float
    is_break_even: bool = False
    requires_additional_cash: bool = False


class CashRunwayOut(BaseModel):
    """Founder-facing runway forecast derived from one simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    verdict: CashRunwayVerdict = "INVIABLE"
    weighted_conversion_rate: float = 0.0
    starting_cash: float = 0.0
    horizon_months: int = 0
    initial_monthly_visitors: int = 0
    monthly_visitor_growth_rate: float = 0.0
    monthly_fixed_costs: float = 0.0
    average_order_value: float = 0.0
    purchases_per_customer_per_month: float = 1.0
    gross_margin: float = 0.0
    cost_per_visitor: float = 0.0
    initial_monthly_burn: float = 0.0
    static_runway_months: float | None = None
    break_even_month: int | None = None
    cash_out_month: int | None = None
    cash_at_break_even: float | None = None
    lowest_cash_balance: float = 0.0
    minimum_additional_cash: float = 0.0
    ending_cash_balance: float = 0.0
    total_revenue: float = 0.0
    total_operating_result: float = 0.0
    trajectory: list[CashRunwayMonthOut] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = ["CashRunwayMonthOut", "CashRunwayOut", "CashRunwayVerdict"]
