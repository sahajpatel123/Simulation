"""Solve for the acquisition-cost ceiling that preserves runway.

The completed simulation supplies expected conversion. Founder inputs supply
cash, traffic growth, and operating economics. This read model searches
blended cost per visitor in exact 0.0001 increments for the largest acquisition
cost that reaches monthly operating break-even inside the selected horizon
without an intervening negative cash balance. It performs no I/O.
"""

from __future__ import annotations

from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_acquisition_ceiling import (
    RunwayAcquisitionCeilingOut,
    RunwayAcquisitionCeilingVerdict,
    RunwayAcquisitionConstraint,
    RunwayAcquisitionScenarioOut,
)
from app.simulation.break_even import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_COST_PER_VISITOR,
    DEFAULT_GROSS_MARGIN,
    DEFAULT_MONTHLY_FIXED_COSTS,
    DEFAULT_MONTHLY_VISITORS,
    DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
    MAX_COST_PER_VISITOR,
)
from app.simulation.cash_runway import (
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    DEFAULT_STARTING_CASH,
    VERDICT_INVIABLE,
    build_cash_runway,
)

COST_PRECISION: int = 4
COST_SCALE: int = 10**COST_PRECISION

VERDICT_PLAN_WITHIN_CEILING: RunwayAcquisitionCeilingVerdict = (
    "PLAN_WITHIN_CEILING"
)
VERDICT_PLAN_EXCEEDS_CEILING: RunwayAcquisitionCeilingVerdict = (
    "PLAN_EXCEEDS_CEILING"
)
VERDICT_INFEASIBLE: RunwayAcquisitionCeilingVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return (
        forecast.verdict != VERDICT_INVIABLE
        and forecast.break_even_month is not None
        and forecast.cash_out_month is None
    )


def _scenario(forecast: CashRunwayOut) -> RunwayAcquisitionScenarioOut:
    return RunwayAcquisitionScenarioOut(
        cost_per_visitor=forecast.cost_per_visitor,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _recommendations(
    *,
    verdict: RunwayAcquisitionCeilingVerdict,
    constraint: RunwayAcquisitionConstraint,
    planned_cost: float,
    ceiling: float | None,
    headroom: float | None,
    required_reduction: float | None,
    signal_quality: float | None,
) -> list[str]:
    if constraint == "UNIT_ECONOMICS":
        recommendations = [
            "No acquisition budget is supportable because the simulation has no positive conversion value per visit; validate conversion, price, purchase frequency, and margin first.",
        ]
    elif constraint == "OPERATING_PLAN":
        recommendations = [
            "Even zero-cost acquisition does not reach break-even while preserving cash inside the selected horizon.",
            "Add opening cash, lower fixed costs, extend the horizon, or strengthen evidence-backed visitor growth before paying for acquisition.",
        ]
    elif constraint == "SEARCH_LIMIT":
        recommendations = [
            f"The plan supports at least {ceiling or 0.0:,.4f} per visitor; the true acquisition ceiling is above the supported search limit.",
            "Use a higher-range finance model before committing acquisition spend above this API limit.",
        ]
    elif verdict == VERDICT_PLAN_WITHIN_CEILING:
        recommendations = [
            f"The planned {planned_cost:,.4f} per visitor is within the cash-safe ceiling of {ceiling or 0.0:,.4f}, leaving {headroom or 0.0:,.4f} per visitor in headroom.",
            "Treat the headroom as a buffer until conversion and channel costs are validated with observed cohorts.",
        ]
    else:
        recommendations = [
            f"Reduce blended acquisition cost by at least {required_reduction or 0.0:,.4f} per visitor, from {planned_cost:,.4f} to the cash-safe ceiling of {ceiling or 0.0:,.4f}.",
            "If that reduction is impractical, close the runway gap with more cash, lower fixed costs, stronger conversion, or higher contribution per customer.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the ceiling as directional because this simulation has low signal quality; validate the weakest assumptions before setting acquisition bids."
        )
    return recommendations


def build_runway_acquisition_ceiling(
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
    planned_cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> RunwayAcquisitionCeilingOut:
    """Return the largest supported cost per visitor that is cash-safe."""

    def forecast(cost_per_visitor: float) -> CashRunwayOut:
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

    planned_forecast = forecast(planned_cost_per_visitor)
    zero_cost_forecast = forecast(0.0)
    maximum_forecast = forecast(MAX_COST_PER_VISITOR)

    ceiling_forecast: CashRunwayOut | None = None
    ceiling: float | None = None
    search_limit_reached = False
    if _succeeds(zero_cost_forecast):
        if _succeeds(maximum_forecast):
            ceiling = MAX_COST_PER_VISITOR
            ceiling_forecast = maximum_forecast
            search_limit_reached = True
        else:
            low_units = 0
            high_units = int(round(MAX_COST_PER_VISITOR * COST_SCALE))
            while high_units - low_units > 1:
                midpoint_units = (low_units + high_units) // 2
                if _succeeds(forecast(midpoint_units / COST_SCALE)):
                    low_units = midpoint_units
                else:
                    high_units = midpoint_units
            ceiling = low_units / COST_SCALE
            ceiling_forecast = forecast(ceiling)
            next_forecast = forecast(high_units / COST_SCALE)
            if not _succeeds(ceiling_forecast) or _succeeds(next_forecast):
                raise RuntimeError(
                    "Derived runway acquisition ceiling failed forecast verification."
                )

    planned_cost = planned_forecast.cost_per_visitor
    headroom: float | None = None
    required_reduction: float | None = None
    if ceiling is None:
        verdict: RunwayAcquisitionCeilingVerdict = VERDICT_INFEASIBLE
        constraint: RunwayAcquisitionConstraint = (
            "UNIT_ECONOMICS"
            if zero_cost_forecast.verdict == VERDICT_INVIABLE
            else "OPERATING_PLAN"
        )
    else:
        headroom = round(max(0.0, ceiling - planned_cost), COST_PRECISION)
        required_reduction = round(
            max(0.0, planned_cost - ceiling),
            COST_PRECISION,
        )
        if _succeeds(planned_forecast):
            verdict = VERDICT_PLAN_WITHIN_CEILING
            constraint = "SEARCH_LIMIT" if search_limit_reached else "NONE"
        else:
            verdict = VERDICT_PLAN_EXCEEDS_CEILING
            constraint = "ACQUISITION_COST_PLAN"

    safe_signal_quality = planned_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        planned_cost=planned_cost,
        ceiling=ceiling,
        headroom=headroom,
        required_reduction=required_reduction,
        signal_quality=safe_signal_quality,
    )

    return RunwayAcquisitionCeilingOut(
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
        monthly_fixed_costs=planned_forecast.monthly_fixed_costs,
        average_order_value=planned_forecast.average_order_value,
        gross_margin=planned_forecast.gross_margin,
        purchases_per_customer_per_month=(
            planned_forecast.purchases_per_customer_per_month
        ),
        planned_cost_per_visitor=planned_cost,
        cash_safe_cost_per_visitor_ceiling=ceiling,
        cost_per_visitor_headroom=headroom,
        required_cost_per_visitor_reduction=required_reduction,
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
            "model": "runway_acquisition_ceiling_v1",
            "search_increment": 1 / COST_SCALE,
            "search_method": "integer_binary_search_with_boundary_verification",
            "maximum_tested_cost_per_visitor": MAX_COST_PER_VISITOR,
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "COST_PRECISION",
    "COST_SCALE",
    "VERDICT_INFEASIBLE",
    "VERDICT_PLAN_EXCEEDS_CEILING",
    "VERDICT_PLAN_WITHIN_CEILING",
    "build_runway_acquisition_ceiling",
]
