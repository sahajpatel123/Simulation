"""Solve for the minimum conversion rate that preserves runway.

The completed simulation supplies the predicted visitor-to-purchase
conversion. Founder inputs supply cash, traffic growth, and operating
economics. This read model searches conversion in exact 0.00000001 increments
for the smallest rate that reaches monthly operating break-even inside the
selected horizon without an intervening negative cash balance. It performs no
database or network I/O.
"""

from __future__ import annotations

from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_conversion_target import (
    RunwayConversionConstraint,
    RunwayConversionScenarioOut,
    RunwayConversionTargetOut,
    RunwayConversionTargetVerdict,
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
    VERDICT_INVIABLE,
    build_cash_runway,
)

CONVERSION_PRECISION: int = 8
CONVERSION_SCALE: int = 10**CONVERSION_PRECISION
MAX_CONVERSION_RATE: float = 1.0

VERDICT_PREDICTION_SUFFICIENT: RunwayConversionTargetVerdict = (
    "PREDICTION_SUFFICIENT"
)
VERDICT_CONVERSION_GAP: RunwayConversionTargetVerdict = "CONVERSION_GAP"
VERDICT_INFEASIBLE: RunwayConversionTargetVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return (
        forecast.verdict != VERDICT_INVIABLE
        and forecast.break_even_month is not None
        and forecast.cash_out_month is None
    )


def _scenario(forecast: CashRunwayOut) -> RunwayConversionScenarioOut:
    return RunwayConversionScenarioOut(
        conversion_rate=forecast.weighted_conversion_rate,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _recommendations(
    *,
    verdict: RunwayConversionTargetVerdict,
    constraint: RunwayConversionConstraint,
    simulated_conversion: float,
    required_conversion: float | None,
    gap_points: float | None,
    headroom_points: float | None,
    relative_lift: float | None,
    signal_quality: float | None,
) -> list[str]:
    if constraint == "UNIT_ECONOMICS":
        recommendations = [
            "Even 100% visitor conversion cannot produce positive per-visit contribution under these price, margin, purchase-frequency, and acquisition-cost inputs.",
            "Improve contribution per customer or reduce acquisition cost before setting a conversion target.",
        ]
    elif constraint == "FIRST_MONTH_CASH":
        recommendations = [
            "Cash turns negative in month 1 even at 100% conversion, before later traffic growth can help.",
            "Add opening cash, lower immediate fixed costs, or improve contribution per customer.",
        ]
    elif constraint == "HORIZON_OR_CASH":
        recommendations = [
            "Even 100% conversion does not reach break-even while preserving cash inside the selected horizon.",
            "Extend the horizon, add opening cash, lower fixed costs, or strengthen traffic and unit economics.",
        ]
    elif verdict == VERDICT_PREDICTION_SUFFICIENT:
        recommendations = [
            f"The simulated {simulated_conversion:.2%} conversion clears the cash-safe {required_conversion or 0.0:.2%} target by {headroom_points or 0.0:.2f} percentage points.",
            "Treat that headroom as a buffer until observed cohorts validate conversion and acquisition costs.",
        ]
    else:
        lift_text = (
            f" requiring {relative_lift:.1f}% relative lift"
            if relative_lift is not None
            else "; relative lift is undefined from a zero-conversion baseline"
        )
        recommendations = [
            f"Raise conversion from the simulated {simulated_conversion:.2%} to at least {required_conversion or 0.0:.2%}, a {gap_points or 0.0:.2f}-point gap{lift_text}.",
            "If that lift is not evidence-backed, close the runway gap with more cash, lower fixed costs, cheaper acquisition, stronger traffic growth, or better contribution per customer.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the target as directional because this simulation has low signal quality; validate the weakest assumptions before funding against it."
        )
    return recommendations


def build_runway_conversion_target(
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
) -> RunwayConversionTargetOut:
    """Return the minimum cash-safe conversion rate for the supplied plan."""

    def forecast(forecast_results: Any) -> CashRunwayOut:
        return build_cash_runway(
            forecast_results,
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

    predicted_forecast = forecast(results)
    predicted_conversion = predicted_forecast.weighted_conversion_rate
    maximum_units = int(round(MAX_CONVERSION_RATE * CONVERSION_SCALE))
    forecast_cache: dict[int, CashRunwayOut] = {}

    def forecast_units(conversion_units: int) -> CashRunwayOut:
        cached = forecast_cache.get(conversion_units)
        if cached is not None:
            return cached
        result = forecast(
            {
                "population_weighted_conversion": (
                    conversion_units / CONVERSION_SCALE
                )
            }
        )
        forecast_cache[conversion_units] = result
        return result

    maximum_forecast = forecast_units(maximum_units)
    required_conversion: float | None = None
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
        required_conversion = high_units / CONVERSION_SCALE
        target_forecast = forecast_units(high_units)
        previous_forecast = forecast_units(low_units)
        if not _succeeds(target_forecast) or _succeeds(previous_forecast):
            raise RuntimeError(
                "Derived runway conversion target failed forecast verification."
            )

    gap_points: float | None = None
    headroom_points: float | None = None
    relative_lift: float | None = None
    if required_conversion is None:
        verdict: RunwayConversionTargetVerdict = VERDICT_INFEASIBLE
        if maximum_forecast.verdict == VERDICT_INVIABLE:
            constraint: RunwayConversionConstraint = "UNIT_ECONOMICS"
        elif maximum_forecast.cash_out_month == 1:
            constraint = "FIRST_MONTH_CASH"
        else:
            constraint = "HORIZON_OR_CASH"
    elif _succeeds(predicted_forecast):
        verdict = VERDICT_PREDICTION_SUFFICIENT
        constraint = "NONE"
        gap_points = 0.0
        headroom_points = round(
            max(0.0, predicted_conversion - required_conversion) * 100.0,
            6,
        )
        relative_lift = 0.0
    else:
        verdict = VERDICT_CONVERSION_GAP
        constraint = "SIMULATED_CONVERSION"
        gap_points = round(
            max(0.0, required_conversion - predicted_conversion) * 100.0,
            6,
        )
        headroom_points = 0.0
        relative_lift = (
            round(
                (required_conversion / predicted_conversion - 1.0) * 100.0,
                2,
            )
            if predicted_conversion > 0.0
            else None
        )

    safe_signal_quality = predicted_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        simulated_conversion=predicted_conversion,
        required_conversion=required_conversion,
        gap_points=gap_points,
        headroom_points=headroom_points,
        relative_lift=relative_lift,
        signal_quality=safe_signal_quality,
    )

    return RunwayConversionTargetOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        constraint=constraint,
        simulated_conversion_rate=predicted_conversion,
        required_conversion_rate=required_conversion,
        conversion_gap_percentage_points=gap_points,
        conversion_headroom_percentage_points=headroom_points,
        relative_conversion_lift_percent=relative_lift,
        starting_cash=predicted_forecast.starting_cash,
        horizon_months=predicted_forecast.horizon_months,
        initial_monthly_visitors=predicted_forecast.initial_monthly_visitors,
        monthly_visitor_growth_rate=(
            predicted_forecast.monthly_visitor_growth_rate
        ),
        monthly_fixed_costs=predicted_forecast.monthly_fixed_costs,
        average_order_value=predicted_forecast.average_order_value,
        gross_margin=predicted_forecast.gross_margin,
        purchases_per_customer_per_month=(
            predicted_forecast.purchases_per_customer_per_month
        ),
        cost_per_visitor=predicted_forecast.cost_per_visitor,
        predicted=_scenario(predicted_forecast),
        target=_scenario(target_forecast) if target_forecast is not None else None,
        maximum_tested=_scenario(maximum_forecast),
        recommendations=recommendations,
        meta={
            "conversion_source": predicted_forecast.meta.get(
                "conversion_source", "none"
            ),
            "signal_quality": safe_signal_quality,
            "model": "runway_conversion_target_v1",
            "search_increment": 1 / CONVERSION_SCALE,
            "search_method": (
                "integer_binary_search_with_boundary_verification"
            ),
            "maximum_tested_conversion_rate": MAX_CONVERSION_RATE,
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "CONVERSION_PRECISION",
    "CONVERSION_SCALE",
    "MAX_CONVERSION_RATE",
    "VERDICT_CONVERSION_GAP",
    "VERDICT_INFEASIBLE",
    "VERDICT_PREDICTION_SUFFICIENT",
    "build_runway_conversion_target",
]
