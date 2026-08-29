"""Cash-runway forecasting from completed simulation results.

The simulation supplies expected visitor-to-customer conversion. Founder
inputs supply cash, traffic growth, and operating economics. The projection
then answers whether cash lasts until monthly operating break-even, identifies
the first cash-negative month, and quantifies the smallest cash bridge needed
across the selected horizon.

This module is deterministic and performs no database or network I/O.
"""
from __future__ import annotations

import math
from typing import Any

from app.schemas.cash_runway import (
    CashRunwayMonthOut,
    CashRunwayOut,
    CashRunwayVerdict,
)
from app.simulation.break_even import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_COST_PER_VISITOR,
    DEFAULT_GROSS_MARGIN,
    DEFAULT_MONTHLY_FIXED_COSTS,
    DEFAULT_MONTHLY_VISITORS,
    DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
    MAX_MONTHLY_VISITORS,
    build_break_even,
)

DEFAULT_STARTING_CASH: float = 50_000.0
MAX_STARTING_CASH: float = 1_000_000_000_000.0
DEFAULT_HORIZON_MONTHS: int = 18
MIN_HORIZON_MONTHS: int = 1
MAX_HORIZON_MONTHS: int = 60
DEFAULT_MONTHLY_VISITOR_GROWTH_RATE: float = 0.10
MAX_MONTHLY_VISITOR_GROWTH_RATE: float = 1.0

VERDICT_SELF_SUSTAINING: CashRunwayVerdict = "SELF_SUSTAINING"
VERDICT_FUNDED_TO_BREAK_EVEN: CashRunwayVerdict = "FUNDED_TO_BREAK_EVEN"
VERDICT_CASH_GAP: CashRunwayVerdict = "CASH_GAP"
VERDICT_BEYOND_HORIZON: CashRunwayVerdict = "BEYOND_HORIZON"
VERDICT_INVIABLE: CashRunwayVerdict = "INVIABLE"


def _safe_float(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: Any, minimum: float, maximum: float, default: float) -> float:
    return max(minimum, min(maximum, _safe_float(value, default)))


def _recommendations(
    *,
    verdict: CashRunwayVerdict,
    break_even_month: int | None,
    cash_out_month: int | None,
    minimum_additional_cash: float,
    lowest_cash_balance: float,
    initial_monthly_burn: float,
    signal_quality: float | None,
) -> list[str]:
    if verdict == VERDICT_INVIABLE:
        recommendations = [
            "Traffic has no positive per-visit contribution at the simulated conversion; improve conversion, margin, or acquisition cost before relying on growth to extend runway.",
            "Reduce fixed burn while validating a positive-contribution acquisition path.",
        ]
    elif verdict == VERDICT_SELF_SUSTAINING:
        recommendations = [
            "The operating model is cash-generative from month 1; protect contribution per visitor as traffic scales.",
            f"Keep a liquidity buffer above the projected low point of {lowest_cash_balance:,.2f}.",
        ]
    elif verdict == VERDICT_FUNDED_TO_BREAK_EVEN:
        recommendations = [
            f"Current cash reaches monthly operating break-even in month {break_even_month} without going negative.",
            f"Protect the projected cash trough of {lowest_cash_balance:,.2f} by reviewing traffic growth and burn monthly.",
        ]
    elif verdict == VERDICT_CASH_GAP:
        timing = (
            f" before projected break-even in month {break_even_month}"
            if break_even_month is not None
            else " within the forecast horizon"
        )
        recommendations = [
            f"Cash turns negative in month {cash_out_month}{timing}; secure at least {minimum_additional_cash:,.2f} or remove the same amount of cumulative burn.",
            "Prioritize changes to fixed costs, conversion, margin, or acquisition cost before increasing traffic spend.",
        ]
    else:
        recommendations = [
            "Cash remains non-negative across the forecast, but monthly operating break-even is not reached within the selected horizon.",
            f"Track the initial monthly burn of {initial_monthly_burn:,.2f} and extend the horizon before making long-lived spending commitments.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat timing as directional because this simulation has low signal quality; validate the weakest assumptions before funding against it."
        )
    return recommendations


def build_cash_runway(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    starting_cash: float = DEFAULT_STARTING_CASH,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    initial_monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    monthly_visitor_growth_rate: float = DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    monthly_fixed_costs: float = DEFAULT_MONTHLY_FIXED_COSTS,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (
        DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH
    ),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> CashRunwayOut:
    """Build a deterministic cash forecast and break-even survival verdict."""
    cash = _clamp(starting_cash, 0.0, MAX_STARTING_CASH, DEFAULT_STARTING_CASH)
    months = max(
        MIN_HORIZON_MONTHS,
        min(
            MAX_HORIZON_MONTHS,
            _safe_int(horizon_months, DEFAULT_HORIZON_MONTHS),
        ),
    )
    growth_rate = _clamp(
        monthly_visitor_growth_rate,
        0.0,
        MAX_MONTHLY_VISITOR_GROWTH_RATE,
        DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    )

    economics = build_break_even(
        results,
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        monthly_visitors=initial_monthly_visitors,
        monthly_fixed_costs=monthly_fixed_costs,
        average_order_value=average_order_value,
        gross_margin=gross_margin,
        purchases_per_customer_per_month=purchases_per_customer_per_month,
        cost_per_visitor=cost_per_visitor,
        signal_quality=signal_quality,
    )

    initial_cash = cash
    lowest_cash = cash
    break_even_month: int | None = None
    cash_out_month: int | None = None
    cash_at_break_even: float | None = None
    total_revenue = 0.0
    total_operating_result = 0.0
    trajectory: list[CashRunwayMonthOut] = []

    for month in range(1, months + 1):
        grown_visitors = economics.monthly_visitors * ((1.0 + growth_rate) ** (month - 1))
        visitors = min(MAX_MONTHLY_VISITORS, int(round(grown_visitors)))
        customers = visitors * economics.weighted_conversion_rate
        revenue = (
            customers
            * economics.average_order_value
            * economics.purchases_per_customer_per_month
        )
        gross_profit = revenue * economics.gross_margin
        acquisition_cost = visitors * economics.cost_per_visitor
        operating_result = (
            gross_profit - acquisition_cost - economics.monthly_fixed_costs
        )
        cash += operating_result
        total_revenue += revenue
        total_operating_result += operating_result
        lowest_cash = min(lowest_cash, cash)

        is_break_even = operating_result >= 0.0
        if is_break_even and break_even_month is None:
            break_even_month = month
            cash_at_break_even = cash
        requires_cash = cash < 0.0
        if requires_cash and cash_out_month is None:
            cash_out_month = month

        trajectory.append(
            CashRunwayMonthOut(
                month=month,
                monthly_visitors=visitors,
                monthly_customers=round(customers, 2),
                monthly_revenue=round(revenue, 2),
                monthly_operating_result=round(operating_result, 2),
                ending_cash_balance=round(cash, 2),
                is_break_even=is_break_even,
                requires_additional_cash=requires_cash,
            )
        )

    initial_monthly_burn = max(0.0, -trajectory[0].monthly_operating_result)
    static_runway_months = (
        initial_cash / initial_monthly_burn if initial_monthly_burn > 0.0 else None
    )
    minimum_additional_cash = max(0.0, -lowest_cash)

    if (
        economics.weighted_conversion_rate <= 0.0
        or economics.contribution_per_visitor <= 0.0
    ):
        verdict: CashRunwayVerdict = VERDICT_INVIABLE
    elif break_even_month == 1:
        verdict = VERDICT_SELF_SUSTAINING
    elif cash_out_month is not None:
        verdict = VERDICT_CASH_GAP
    elif break_even_month is not None:
        verdict = VERDICT_FUNDED_TO_BREAK_EVEN
    else:
        verdict = VERDICT_BEYOND_HORIZON

    safe_signal_quality = (
        _clamp(signal_quality, 0.0, 1.0, 0.0)
        if signal_quality is not None
        else None
    )
    recommendations = _recommendations(
        verdict=verdict,
        break_even_month=break_even_month,
        cash_out_month=cash_out_month,
        minimum_additional_cash=minimum_additional_cash,
        lowest_cash_balance=lowest_cash,
        initial_monthly_burn=initial_monthly_burn,
        signal_quality=safe_signal_quality,
    )

    return CashRunwayOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        weighted_conversion_rate=economics.weighted_conversion_rate,
        starting_cash=round(initial_cash, 2),
        horizon_months=months,
        initial_monthly_visitors=economics.monthly_visitors,
        monthly_visitor_growth_rate=round(growth_rate, 6),
        monthly_fixed_costs=economics.monthly_fixed_costs,
        average_order_value=economics.average_order_value,
        purchases_per_customer_per_month=(
            economics.purchases_per_customer_per_month
        ),
        gross_margin=economics.gross_margin,
        cost_per_visitor=economics.cost_per_visitor,
        initial_monthly_burn=round(initial_monthly_burn, 2),
        static_runway_months=(
            round(static_runway_months, 2)
            if static_runway_months is not None
            else None
        ),
        break_even_month=break_even_month,
        cash_out_month=cash_out_month,
        cash_at_break_even=(
            round(cash_at_break_even, 2)
            if cash_at_break_even is not None
            else None
        ),
        lowest_cash_balance=round(lowest_cash, 2),
        minimum_additional_cash=round(minimum_additional_cash, 2),
        ending_cash_balance=round(cash, 2),
        total_revenue=round(total_revenue, 2),
        total_operating_result=round(total_operating_result, 2),
        trajectory=trajectory,
        recommendations=recommendations,
        meta={
            "conversion_source": economics.meta.get("conversion_source", "none"),
            "signal_quality": safe_signal_quality,
            "model": "cash_runway_growth_v1",
            "assumptions": "constant conversion, margin, costs, and monthly visitor growth",
        },
    )


__all__ = [
    "DEFAULT_HORIZON_MONTHS",
    "DEFAULT_MONTHLY_VISITOR_GROWTH_RATE",
    "DEFAULT_STARTING_CASH",
    "MAX_HORIZON_MONTHS",
    "MAX_MONTHLY_VISITOR_GROWTH_RATE",
    "MAX_STARTING_CASH",
    "MIN_HORIZON_MONTHS",
    "VERDICT_BEYOND_HORIZON",
    "VERDICT_CASH_GAP",
    "VERDICT_FUNDED_TO_BREAK_EVEN",
    "VERDICT_INVIABLE",
    "VERDICT_SELF_SUSTAINING",
    "build_cash_runway",
]
