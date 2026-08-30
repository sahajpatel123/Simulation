"""Solve for the minimum average order value that preserves runway.

The completed simulation supplies expected visitor-to-purchase conversion.
Founder inputs supply cash, traffic growth, margin, purchase frequency, and
costs. This read model searches average order value in exact cent increments
for the smallest price that reaches monthly operating break-even inside the
selected horizon without an intervening negative cash balance. It performs no
database or network I/O.
"""

from __future__ import annotations

from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_price_target import (
    RunwayPriceConstraint,
    RunwayPriceScenarioOut,
    RunwayPriceTargetOut,
    RunwayPriceTargetVerdict,
)
from app.simulation.break_even import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_COST_PER_VISITOR,
    DEFAULT_GROSS_MARGIN,
    DEFAULT_MONTHLY_FIXED_COSTS,
    DEFAULT_MONTHLY_VISITORS,
    DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
    MAX_AVERAGE_ORDER_VALUE,
)
from app.simulation.cash_runway import (
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    DEFAULT_STARTING_CASH,
    VERDICT_INVIABLE,
    build_cash_runway,
)

MONEY_SCALE: int = 100

VERDICT_PLAN_PRICE_SUFFICIENT: RunwayPriceTargetVerdict = (
    "PLAN_PRICE_SUFFICIENT"
)
VERDICT_PRICE_GAP: RunwayPriceTargetVerdict = "PRICE_GAP"
VERDICT_INFEASIBLE: RunwayPriceTargetVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return (
        forecast.verdict != VERDICT_INVIABLE
        and forecast.break_even_month is not None
        and forecast.cash_out_month is None
    )


def _scenario(forecast: CashRunwayOut) -> RunwayPriceScenarioOut:
    return RunwayPriceScenarioOut(
        average_order_value=forecast.average_order_value,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _recommendations(
    *,
    verdict: RunwayPriceTargetVerdict,
    constraint: RunwayPriceConstraint,
    planned_price: float,
    required_price: float | None,
    headroom: float | None,
    required_increase: float | None,
    relative_increase: float | None,
    signal_quality: float | None,
) -> list[str]:
    if constraint == "DEMAND_SIGNAL":
        recommendations = [
            "No positive conversion signal is available, so price alone cannot create a cash-safe runway.",
            "Validate demand and re-run the simulation before setting a runway-backed price target.",
        ]
    elif constraint == "MARGIN_OR_FREQUENCY":
        recommendations = [
            "Price cannot create contribution while gross margin or purchase frequency is zero.",
            "Establish positive margin and a credible purchase model before relying on revenue to fund runway.",
        ]
    elif constraint == "SUPPORTED_PRICE_LIMIT":
        recommendations = [
            f"Even the maximum tested average order value of {MAX_AVERAGE_ORDER_VALUE:,.2f} does not preserve cash to break-even.",
            "Add opening cash, reduce fixed or acquisition costs, extend the horizon, or improve evidence-backed conversion and traffic growth.",
        ]
    elif verdict == VERDICT_PLAN_PRICE_SUFFICIENT:
        recommendations = [
            f"The planned average order value of {planned_price:,.2f} clears the cash-safe target of {required_price or 0.0:,.2f} by {headroom or 0.0:,.2f}.",
            "Protect that price headroom until observed conversion, margin, and acquisition costs validate the plan.",
        ]
    else:
        relative_text = (
            f", a {relative_increase:.1f}% increase"
            if relative_increase is not None
            else "; the relative increase is undefined from a zero-price baseline"
        )
        recommendations = [
            f"Raise average order value by at least {required_increase or 0.0:,.2f}, from {planned_price:,.2f} to {required_price or 0.0:,.2f}{relative_text}.",
            "Validate willingness to pay before funding against the target; otherwise close the gap with lower costs, more cash, or stronger conversion.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the price target as directional because this simulation has low signal quality; validate the weakest assumptions before changing pricing."
        )
    return recommendations


def build_runway_price_target(
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
    planned_average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (
        DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH
    ),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> RunwayPriceTargetOut:
    """Return the minimum cent-denominated price that is cash-safe."""

    def forecast(average_order_value: float) -> CashRunwayOut:
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

    preflight = forecast(planned_average_order_value)
    planned_units = int(round(preflight.average_order_value * MONEY_SCALE))
    maximum_units = int(round(MAX_AVERAGE_ORDER_VALUE * MONEY_SCALE))
    forecast_cache: dict[int, CashRunwayOut] = {}

    def forecast_units(price_units: int) -> CashRunwayOut:
        cached = forecast_cache.get(price_units)
        if cached is not None:
            return cached
        result = forecast(price_units / MONEY_SCALE)
        forecast_cache[price_units] = result
        return result

    planned_forecast = forecast_units(planned_units)
    maximum_forecast = forecast_units(maximum_units)
    required_price: float | None = None
    target_forecast: CashRunwayOut | None = None
    if _succeeds(maximum_forecast):
        low_units = 0
        high_units = maximum_units
        while high_units - low_units > 1:
            midpoint_units = (low_units + high_units) // 2
            if _succeeds(forecast_units(midpoint_units)):
                high_units = midpoint_units
            else:
                low_units = midpoint_units
        required_price = high_units / MONEY_SCALE
        target_forecast = forecast_units(high_units)
        previous_forecast = forecast_units(low_units)
        if not _succeeds(target_forecast) or _succeeds(previous_forecast):
            raise RuntimeError(
                "Derived runway price target failed forecast verification."
            )

    planned_price = planned_forecast.average_order_value
    headroom: float | None = None
    required_increase: float | None = None
    relative_increase: float | None = None
    if required_price is None:
        verdict: RunwayPriceTargetVerdict = VERDICT_INFEASIBLE
        if planned_forecast.weighted_conversion_rate <= 0.0:
            constraint: RunwayPriceConstraint = "DEMAND_SIGNAL"
        elif (
            planned_forecast.gross_margin <= 0.0
            or planned_forecast.purchases_per_customer_per_month <= 0.0
        ):
            constraint = "MARGIN_OR_FREQUENCY"
        else:
            constraint = "SUPPORTED_PRICE_LIMIT"
    else:
        headroom = round(max(0.0, planned_price - required_price), 2)
        required_increase = round(max(0.0, required_price - planned_price), 2)
        if _succeeds(planned_forecast):
            verdict = VERDICT_PLAN_PRICE_SUFFICIENT
            constraint = "NONE"
            relative_increase = 0.0
        else:
            verdict = VERDICT_PRICE_GAP
            constraint = "PRICE_PLAN"
            relative_increase = (
                round((required_price / planned_price - 1.0) * 100.0, 2)
                if planned_price > 0.0
                else None
            )

    safe_signal_quality = planned_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        planned_price=planned_price,
        required_price=required_price,
        headroom=headroom,
        required_increase=required_increase,
        relative_increase=relative_increase,
        signal_quality=safe_signal_quality,
    )

    return RunwayPriceTargetOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        constraint=constraint,
        weighted_conversion_rate=planned_forecast.weighted_conversion_rate,
        starting_cash=planned_forecast.starting_cash,
        horizon_months=planned_forecast.horizon_months,
        initial_monthly_visitors=planned_forecast.initial_monthly_visitors,
        monthly_visitor_growth_rate=planned_forecast.monthly_visitor_growth_rate,
        monthly_fixed_costs=planned_forecast.monthly_fixed_costs,
        planned_average_order_value=planned_price,
        gross_margin=planned_forecast.gross_margin,
        purchases_per_customer_per_month=(
            planned_forecast.purchases_per_customer_per_month
        ),
        cost_per_visitor=planned_forecast.cost_per_visitor,
        required_average_order_value=required_price,
        price_headroom=headroom,
        required_price_increase=required_increase,
        relative_price_increase_percent=relative_increase,
        planned=_scenario(planned_forecast),
        target=(
            _scenario(target_forecast) if target_forecast is not None else None
        ),
        maximum_tested=_scenario(maximum_forecast),
        recommendations=recommendations,
        meta={
            "conversion_source": planned_forecast.meta.get(
                "conversion_source", "none"
            ),
            "signal_quality": safe_signal_quality,
            "model": "runway_price_target_v1",
            "search_increment": 1 / MONEY_SCALE,
            "search_method": (
                "integer_binary_search_with_boundary_verification"
            ),
            "maximum_tested_average_order_value": MAX_AVERAGE_ORDER_VALUE,
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "MONEY_SCALE",
    "VERDICT_INFEASIBLE",
    "VERDICT_PLAN_PRICE_SUFFICIENT",
    "VERDICT_PRICE_GAP",
    "build_runway_price_target",
]
