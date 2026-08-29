"""Solve for the recurring fixed-cost ceiling that preserves runway.

The completed simulation supplies expected conversion. Founder inputs supply
cash, traffic growth, and unit economics. This read model searches fixed costs
in exact cent increments for the largest monthly budget that reaches operating
break-even inside the horizon without an intervening negative cash balance.
It performs no database or network I/O.
"""

from __future__ import annotations

from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_spend_ceiling import (
    RunwaySpendCeilingConstraint,
    RunwaySpendCeilingOut,
    RunwaySpendCeilingVerdict,
    RunwaySpendScenarioOut,
)
from app.simulation.break_even import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_COST_PER_VISITOR,
    DEFAULT_GROSS_MARGIN,
    DEFAULT_MONTHLY_FIXED_COSTS,
    DEFAULT_MONTHLY_VISITORS,
    DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
    MAX_MONTHLY_FIXED_COSTS,
)
from app.simulation.cash_runway import (
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    DEFAULT_STARTING_CASH,
    VERDICT_INVIABLE,
    build_cash_runway,
)

MONEY_SCALE: int = 100

VERDICT_PLAN_WITHIN_CEILING: RunwaySpendCeilingVerdict = "PLAN_WITHIN_CEILING"
VERDICT_PLAN_EXCEEDS_CEILING: RunwaySpendCeilingVerdict = "PLAN_EXCEEDS_CEILING"
VERDICT_INFEASIBLE: RunwaySpendCeilingVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return (
        forecast.verdict != VERDICT_INVIABLE
        and forecast.break_even_month is not None
        and forecast.cash_out_month is None
    )


def _scenario(forecast: CashRunwayOut) -> RunwaySpendScenarioOut:
    return RunwaySpendScenarioOut(
        monthly_fixed_costs=forecast.monthly_fixed_costs,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _recommendations(
    *,
    verdict: RunwaySpendCeilingVerdict,
    constraint: RunwaySpendCeilingConstraint,
    planned_costs: float,
    ceiling: float | None,
    headroom: float | None,
    required_reduction: float | None,
    signal_quality: float | None,
) -> list[str]:
    if verdict == VERDICT_INFEASIBLE:
        recommendations = [
            "No recurring fixed-cost budget is cash-safe because each additional visit has no positive contribution; improve conversion, margin, price, or acquisition cost first.",
        ]
    elif constraint == "SEARCH_LIMIT":
        recommendations = [
            f"The model supports at least {ceiling or 0.0:,.2f} in monthly fixed costs; the true ceiling is above the supported search limit.",
            "Use a higher-resolution finance model before expanding recurring commitments beyond this API limit.",
        ]
    elif verdict == VERDICT_PLAN_WITHIN_CEILING:
        recommendations = [
            f"Planned monthly fixed costs of {planned_costs:,.2f} are within the cash-safe ceiling of {ceiling or 0.0:,.2f}, leaving {headroom or 0.0:,.2f} in monthly headroom.",
            "Treat the headroom as a buffer until visitor growth and conversion are validated with observed cohorts.",
        ]
    else:
        recommendations = [
            f"Reduce recurring fixed costs by at least {required_reduction or 0.0:,.2f} per month, from {planned_costs:,.2f} to the cash-safe ceiling of {ceiling or 0.0:,.2f}.",
            "If those cuts are not practical, close the runway gap with more starting cash, faster evidence-backed growth, or stronger contribution per visit.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the ceiling as directional because this simulation has low signal quality; validate the weakest assumptions before setting recurring spend."
        )
    return recommendations


def build_runway_spend_ceiling(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    starting_cash: float = DEFAULT_STARTING_CASH,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    initial_monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    monthly_visitor_growth_rate: float = DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    planned_monthly_fixed_costs: float = DEFAULT_MONTHLY_FIXED_COSTS,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (
        DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH
    ),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> RunwaySpendCeilingOut:
    """Return the largest cent-denominated fixed-cost budget that is cash-safe."""

    def forecast(monthly_fixed_costs: float) -> CashRunwayOut:
        return build_cash_runway(
            results,
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            starting_cash=starting_cash,
            horizon_months=horizon_months,
            initial_monthly_visitors=initial_monthly_visitors,
            monthly_visitor_growth_rate=monthly_visitor_growth_rate,
            monthly_fixed_costs=monthly_fixed_costs,
            average_order_value=average_order_value,
            gross_margin=gross_margin,
            purchases_per_customer_per_month=purchases_per_customer_per_month,
            cost_per_visitor=cost_per_visitor,
            signal_quality=signal_quality,
        )

    planned_forecast = forecast(planned_monthly_fixed_costs)
    zero_cost_forecast = forecast(0.0)
    maximum_forecast = forecast(MAX_MONTHLY_FIXED_COSTS)

    ceiling_forecast: CashRunwayOut | None = None
    ceiling: float | None = None
    search_limit_reached = False
    if _succeeds(zero_cost_forecast):
        if _succeeds(maximum_forecast):
            ceiling = MAX_MONTHLY_FIXED_COSTS
            ceiling_forecast = maximum_forecast
            search_limit_reached = True
        else:
            low_units = 0
            high_units = int(round(MAX_MONTHLY_FIXED_COSTS * MONEY_SCALE))
            while high_units - low_units > 1:
                midpoint_units = (low_units + high_units) // 2
                if _succeeds(forecast(midpoint_units / MONEY_SCALE)):
                    low_units = midpoint_units
                else:
                    high_units = midpoint_units
            ceiling = low_units / MONEY_SCALE
            ceiling_forecast = forecast(ceiling)

    planned_costs = planned_forecast.monthly_fixed_costs
    headroom: float | None = None
    required_reduction: float | None = None
    if ceiling is None:
        verdict: RunwaySpendCeilingVerdict = VERDICT_INFEASIBLE
        constraint: RunwaySpendCeilingConstraint = "UNIT_ECONOMICS"
    else:
        headroom = round(max(0.0, ceiling - planned_costs), 2)
        required_reduction = round(max(0.0, planned_costs - ceiling), 2)
        if _succeeds(planned_forecast):
            verdict = VERDICT_PLAN_WITHIN_CEILING
            constraint = "SEARCH_LIMIT" if search_limit_reached else "NONE"
        else:
            verdict = VERDICT_PLAN_EXCEEDS_CEILING
            constraint = "FIXED_COST_PLAN"

    safe_signal_quality = planned_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        planned_costs=planned_costs,
        ceiling=ceiling,
        headroom=headroom,
        required_reduction=required_reduction,
        signal_quality=safe_signal_quality,
    )

    return RunwaySpendCeilingOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        constraint=constraint,
        weighted_conversion_rate=planned_forecast.weighted_conversion_rate,
        starting_cash=planned_forecast.starting_cash,
        horizon_months=planned_forecast.horizon_months,
        initial_monthly_visitors=planned_forecast.initial_monthly_visitors,
        monthly_visitor_growth_rate=(planned_forecast.monthly_visitor_growth_rate),
        planned_monthly_fixed_costs=planned_costs,
        average_order_value=planned_forecast.average_order_value,
        gross_margin=planned_forecast.gross_margin,
        purchases_per_customer_per_month=(
            planned_forecast.purchases_per_customer_per_month
        ),
        cost_per_visitor=planned_forecast.cost_per_visitor,
        cash_safe_monthly_fixed_cost_ceiling=ceiling,
        monthly_fixed_cost_headroom=headroom,
        required_monthly_cost_reduction=required_reduction,
        search_limit_reached=search_limit_reached,
        planned=_scenario(planned_forecast),
        ceiling=(
            _scenario(ceiling_forecast) if ceiling_forecast is not None else None
        ),
        recommendations=recommendations,
        meta={
            "conversion_source": planned_forecast.meta.get(
                "conversion_source", "none"
            ),
            "signal_quality": safe_signal_quality,
            "model": "runway_spend_ceiling_v2",
            "search_increment": 1 / MONEY_SCALE,
            "search_method": "integer_binary_search",
            "maximum_tested_monthly_fixed_costs": MAX_MONTHLY_FIXED_COSTS,
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "MONEY_SCALE",
    "VERDICT_INFEASIBLE",
    "VERDICT_PLAN_EXCEEDS_CEILING",
    "VERDICT_PLAN_WITHIN_CEILING",
    "build_runway_spend_ceiling",
]
