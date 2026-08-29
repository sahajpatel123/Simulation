"""Solve for the minimum visitor growth that preserves cash to break-even.

This read model builds on the deterministic cash-runway forecast. It searches
the supported monthly visitor-growth range for the smallest rate that reaches
monthly operating break-even without an intervening negative cash balance.
No database or network I/O is performed here.
"""

from __future__ import annotations

import math
from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_growth_target import (
    RunwayGrowthConstraint,
    RunwayGrowthScenarioOut,
    RunwayGrowthTargetOut,
    RunwayGrowthTargetVerdict,
)
from app.simulation.break_even import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_COST_PER_VISITOR,
    DEFAULT_GROSS_MARGIN,
    DEFAULT_MONTHLY_FIXED_COSTS,
    DEFAULT_MONTHLY_VISITORS,
    DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
)
from app.simulation.cash_runway import (
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    DEFAULT_STARTING_CASH,
    MAX_MONTHLY_VISITOR_GROWTH_RATE,
    VERDICT_INVIABLE,
    build_cash_runway,
)

GROWTH_RATE_PRECISION: int = 6
_SEARCH_ITERATIONS: int = 48

VERDICT_NO_GROWTH_REQUIRED: RunwayGrowthTargetVerdict = "NO_GROWTH_REQUIRED"
VERDICT_PLAN_SUFFICIENT: RunwayGrowthTargetVerdict = "PLAN_SUFFICIENT"
VERDICT_GROWTH_GAP: RunwayGrowthTargetVerdict = "GROWTH_GAP"
VERDICT_INFEASIBLE: RunwayGrowthTargetVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return forecast.break_even_month is not None and forecast.cash_out_month is None


def _scenario(forecast: CashRunwayOut) -> RunwayGrowthScenarioOut:
    return RunwayGrowthScenarioOut(
        monthly_visitor_growth_rate=forecast.monthly_visitor_growth_rate,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _recommendations(
    *,
    verdict: RunwayGrowthTargetVerdict,
    constraint: RunwayGrowthConstraint,
    planned_growth: float,
    required_growth: float | None,
    gap_percentage_points: float | None,
    maximum_growth: float,
    signal_quality: float | None,
) -> list[str]:
    if verdict == VERDICT_NO_GROWTH_REQUIRED:
        recommendations = [
            "Current month-1 traffic already reaches monthly operating break-even; validate retention and contribution before adding acquisition spend.",
        ]
    elif verdict == VERDICT_PLAN_SUFFICIENT:
        recommendations = [
            f"The planned {planned_growth:.2%} monthly visitor growth clears the minimum {required_growth or 0.0:.2%} target without exhausting cash.",
            "Track actual visitor growth and cash monthly so a missed acquisition milestone is visible before the projected cash trough.",
        ]
    elif verdict == VERDICT_GROWTH_GAP:
        recommendations = [
            f"Raise compounded monthly visitor growth from {planned_growth:.2%} to at least {required_growth or 0.0:.2%}, a {gap_percentage_points or 0.0:.2f}-point gap.",
            "If that growth target is not evidence-backed, close the gap with more starting cash, lower fixed costs, stronger conversion, or better contribution per visit.",
        ]
    elif constraint == "UNIT_ECONOMICS":
        recommendations = [
            "Visitor growth cannot create runway because each additional visit has no positive contribution; improve conversion, margin, price, or acquisition cost first.",
        ]
    elif constraint == "FIRST_MONTH_CASH":
        recommendations = [
            "Cash turns negative in month 1, before compounded visitor growth can help; add opening cash or reduce immediate burn.",
        ]
    else:
        recommendations = [
            f"Even {maximum_growth:.0%} monthly visitor growth does not reach break-even while preserving cash inside the selected horizon.",
            "Extend runway or reduce the break-even traffic threshold before committing to a growth-led plan.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the target as directional because this simulation has low signal quality; validate the weakest assumptions before funding against it."
        )
    return recommendations


def build_runway_growth_target(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    starting_cash: float = DEFAULT_STARTING_CASH,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    initial_monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    planned_monthly_visitor_growth_rate: float = (DEFAULT_MONTHLY_VISITOR_GROWTH_RATE),
    monthly_fixed_costs: float = DEFAULT_MONTHLY_FIXED_COSTS,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> RunwayGrowthTargetOut:
    """Return the minimum supported monthly growth rate for runway survival."""

    def forecast(growth_rate: float) -> CashRunwayOut:
        return build_cash_runway(
            results,
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            starting_cash=starting_cash,
            horizon_months=horizon_months,
            initial_monthly_visitors=initial_monthly_visitors,
            monthly_visitor_growth_rate=growth_rate,
            monthly_fixed_costs=monthly_fixed_costs,
            average_order_value=average_order_value,
            gross_margin=gross_margin,
            purchases_per_customer_per_month=purchases_per_customer_per_month,
            cost_per_visitor=cost_per_visitor,
            signal_quality=signal_quality,
        )

    planned_forecast = forecast(planned_monthly_visitor_growth_rate)
    zero_growth_forecast = forecast(0.0)
    maximum_forecast = forecast(MAX_MONTHLY_VISITOR_GROWTH_RATE)

    required_growth: float | None = None
    target_forecast: CashRunwayOut | None = None
    if _succeeds(zero_growth_forecast):
        required_growth = 0.0
        target_forecast = zero_growth_forecast
    elif _succeeds(maximum_forecast):
        low = 0.0
        high = MAX_MONTHLY_VISITOR_GROWTH_RATE
        for _ in range(_SEARCH_ITERATIONS):
            midpoint = (low + high) / 2.0
            if _succeeds(forecast(midpoint)):
                high = midpoint
            else:
                low = midpoint
        scale = 10**GROWTH_RATE_PRECISION
        required_growth = min(
            MAX_MONTHLY_VISITOR_GROWTH_RATE,
            math.ceil(high * scale) / scale,
        )
        target_forecast = forecast(required_growth)

    planned_growth = planned_forecast.monthly_visitor_growth_rate
    gap_percentage_points: float | None = None
    if required_growth is None:
        verdict: RunwayGrowthTargetVerdict = VERDICT_INFEASIBLE
        if maximum_forecast.verdict == VERDICT_INVIABLE:
            constraint: RunwayGrowthConstraint = "UNIT_ECONOMICS"
        elif maximum_forecast.cash_out_month == 1:
            constraint = "FIRST_MONTH_CASH"
        else:
            constraint = "HORIZON_OR_CASH"
    elif required_growth == 0.0:
        verdict = VERDICT_NO_GROWTH_REQUIRED
        constraint = "NONE"
        gap_percentage_points = 0.0
    elif _succeeds(planned_forecast):
        verdict = VERDICT_PLAN_SUFFICIENT
        constraint = "NONE"
        gap_percentage_points = 0.0
    else:
        verdict = VERDICT_GROWTH_GAP
        constraint = "GROWTH_PLAN"
        gap_percentage_points = round(
            max(0.0, required_growth - planned_growth) * 100.0,
            4,
        )

    safe_signal_quality = planned_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        planned_growth=planned_growth,
        required_growth=required_growth,
        gap_percentage_points=gap_percentage_points,
        maximum_growth=MAX_MONTHLY_VISITOR_GROWTH_RATE,
        signal_quality=safe_signal_quality,
    )

    return RunwayGrowthTargetOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        constraint=constraint,
        weighted_conversion_rate=planned_forecast.weighted_conversion_rate,
        starting_cash=planned_forecast.starting_cash,
        horizon_months=planned_forecast.horizon_months,
        initial_monthly_visitors=planned_forecast.initial_monthly_visitors,
        monthly_fixed_costs=planned_forecast.monthly_fixed_costs,
        average_order_value=planned_forecast.average_order_value,
        gross_margin=planned_forecast.gross_margin,
        purchases_per_customer_per_month=(planned_forecast.purchases_per_customer_per_month),
        cost_per_visitor=planned_forecast.cost_per_visitor,
        required_monthly_visitor_growth_rate=required_growth,
        growth_gap_percentage_points=gap_percentage_points,
        planned=_scenario(planned_forecast),
        target=_scenario(target_forecast) if target_forecast is not None else None,
        maximum_tested=_scenario(maximum_forecast),
        recommendations=recommendations,
        meta={
            "conversion_source": planned_forecast.meta.get("conversion_source", "none"),
            "signal_quality": safe_signal_quality,
            "model": "runway_growth_target_v1",
            "search_precision": GROWTH_RATE_PRECISION,
            "maximum_tested_monthly_growth_rate": (MAX_MONTHLY_VISITOR_GROWTH_RATE),
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "GROWTH_RATE_PRECISION",
    "VERDICT_GROWTH_GAP",
    "VERDICT_INFEASIBLE",
    "VERDICT_NO_GROWTH_REQUIRED",
    "VERDICT_PLAN_SUFFICIENT",
    "build_runway_growth_target",
]
