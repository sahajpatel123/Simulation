"""Calculate the opening cash required to preserve runway to break-even.

The completed simulation supplies expected conversion. Founder inputs supply
traffic growth and operating economics. Because opening cash shifts every
monthly balance by the same amount, the cash trough of a zero-cash forecast
gives the exact cent-denominated funding requirement without a search.
This module performs no database or network I/O.
"""

from __future__ import annotations

from typing import Any

from app.schemas.cash_runway import CashRunwayOut
from app.schemas.runway_funding_target import (
    RunwayFundingConstraint,
    RunwayFundingScenarioOut,
    RunwayFundingTargetOut,
    RunwayFundingTargetVerdict,
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

VERDICT_PLAN_FUNDED: RunwayFundingTargetVerdict = "PLAN_FUNDED"
VERDICT_FUNDING_GAP: RunwayFundingTargetVerdict = "FUNDING_GAP"
VERDICT_INFEASIBLE: RunwayFundingTargetVerdict = "INFEASIBLE"


def _succeeds(forecast: CashRunwayOut) -> bool:
    return (
        forecast.verdict != VERDICT_INVIABLE
        and forecast.break_even_month is not None
        and forecast.cash_out_month is None
    )


def _scenario(forecast: CashRunwayOut) -> RunwayFundingScenarioOut:
    return RunwayFundingScenarioOut(
        starting_cash=forecast.starting_cash,
        break_even_month=forecast.break_even_month,
        cash_out_month=forecast.cash_out_month,
        lowest_cash_balance=forecast.lowest_cash_balance,
        ending_cash_balance=forecast.ending_cash_balance,
        succeeds=_succeeds(forecast),
    )


def _target_scenario(
    zero_cash_forecast: CashRunwayOut,
    minimum_starting_cash: float,
) -> RunwayFundingScenarioOut:
    """Shift the zero-cash ledger by the exact required opening balance."""
    return RunwayFundingScenarioOut(
        starting_cash=minimum_starting_cash,
        break_even_month=zero_cash_forecast.break_even_month,
        cash_out_month=None,
        lowest_cash_balance=round(
            zero_cash_forecast.lowest_cash_balance + minimum_starting_cash,
            2,
        ),
        ending_cash_balance=round(
            zero_cash_forecast.ending_cash_balance + minimum_starting_cash,
            2,
        ),
        succeeds=True,
    )


def _recommendations(
    *,
    verdict: RunwayFundingTargetVerdict,
    constraint: RunwayFundingConstraint,
    planned_cash: float,
    minimum_cash: float | None,
    additional_cash: float | None,
    surplus: float | None,
    break_even_month: int | None,
    signal_quality: float | None,
) -> list[str]:
    if constraint == "UNIT_ECONOMICS":
        recommendations = [
            "More opening cash cannot create a sustainable runway because each additional visit has no positive contribution; improve conversion, margin, price, or acquisition cost first.",
        ]
    elif constraint == "BREAK_EVEN_HORIZON":
        recommendations = [
            "The current operating plan does not reach monthly break-even inside the selected horizon, so a break-even funding target is not available.",
            "Extend the horizon or improve growth, fixed costs, conversion, margin, price, or acquisition cost before setting a raise target.",
        ]
    elif verdict == VERDICT_PLAN_FUNDED:
        recommendations = [
            f"The planned opening cash of {planned_cash:,.2f} covers the minimum {minimum_cash or 0.0:,.2f} needed to reach break-even in month {break_even_month}, leaving a {surplus or 0.0:,.2f} buffer.",
            "Keep the buffer uncommitted until visitor growth and conversion are validated with observed cohorts.",
        ]
    else:
        recommendations = [
            f"Add at least {additional_cash or 0.0:,.2f} to the planned {planned_cash:,.2f} opening cash to reach the {minimum_cash or 0.0:,.2f} funding target.",
            "If raising that amount is impractical, close the gap with lower fixed costs, evidence-backed growth, or stronger contribution per visit.",
        ]

    if signal_quality is not None and signal_quality < 0.50:
        recommendations.append(
            "Treat the funding target as directional because this simulation has low signal quality; validate the weakest assumptions before raising against it."
        )
    return recommendations


def build_runway_funding_target(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    planned_starting_cash: float = DEFAULT_STARTING_CASH,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    initial_monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    monthly_visitor_growth_rate: float = DEFAULT_MONTHLY_VISITOR_GROWTH_RATE,
    monthly_fixed_costs: float = DEFAULT_MONTHLY_FIXED_COSTS,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> RunwayFundingTargetOut:
    """Return the exact opening-cash requirement for the supplied plan."""

    def forecast(starting_cash: float) -> CashRunwayOut:
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

    planned_forecast = forecast(planned_starting_cash)
    zero_cash_forecast = forecast(0.0)

    minimum_cash: float | None = None
    additional_cash: float | None = None
    surplus: float | None = None
    target: RunwayFundingScenarioOut | None = None
    if zero_cash_forecast.verdict == VERDICT_INVIABLE:
        verdict: RunwayFundingTargetVerdict = VERDICT_INFEASIBLE
        constraint: RunwayFundingConstraint = "UNIT_ECONOMICS"
    elif zero_cash_forecast.break_even_month is None:
        verdict = VERDICT_INFEASIBLE
        constraint = "BREAK_EVEN_HORIZON"
    else:
        minimum_cash = zero_cash_forecast.minimum_additional_cash
        planned_cash = planned_forecast.starting_cash
        additional_cash = round(max(0.0, minimum_cash - planned_cash), 2)
        surplus = round(max(0.0, planned_cash - minimum_cash), 2)
        target = _target_scenario(zero_cash_forecast, minimum_cash)
        if _succeeds(planned_forecast):
            verdict = VERDICT_PLAN_FUNDED
            constraint = "NONE"
        else:
            verdict = VERDICT_FUNDING_GAP
            constraint = "STARTING_CASH"

    safe_signal_quality = planned_forecast.meta.get("signal_quality")
    recommendations = _recommendations(
        verdict=verdict,
        constraint=constraint,
        planned_cash=planned_forecast.starting_cash,
        minimum_cash=minimum_cash,
        additional_cash=additional_cash,
        surplus=surplus,
        break_even_month=zero_cash_forecast.break_even_month,
        signal_quality=safe_signal_quality,
    )

    return RunwayFundingTargetOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        constraint=constraint,
        weighted_conversion_rate=planned_forecast.weighted_conversion_rate,
        planned_starting_cash=planned_forecast.starting_cash,
        horizon_months=planned_forecast.horizon_months,
        initial_monthly_visitors=planned_forecast.initial_monthly_visitors,
        monthly_visitor_growth_rate=planned_forecast.monthly_visitor_growth_rate,
        monthly_fixed_costs=planned_forecast.monthly_fixed_costs,
        average_order_value=planned_forecast.average_order_value,
        gross_margin=planned_forecast.gross_margin,
        purchases_per_customer_per_month=(planned_forecast.purchases_per_customer_per_month),
        cost_per_visitor=planned_forecast.cost_per_visitor,
        minimum_starting_cash=minimum_cash,
        additional_cash_required=additional_cash,
        funding_surplus=surplus,
        planned=_scenario(planned_forecast),
        target=target,
        recommendations=recommendations,
        meta={
            "conversion_source": planned_forecast.meta.get("conversion_source", "none"),
            "signal_quality": safe_signal_quality,
            "model": "runway_funding_target_v1",
            "calculation_method": "zero_cash_ledger_trough",
            "currency_precision": 0.01,
            "success_definition": (
                "monthly operating break-even inside the horizon without a "
                "negative ending cash balance in any month"
            ),
        },
    )


__all__ = [
    "VERDICT_FUNDING_GAP",
    "VERDICT_INFEASIBLE",
    "VERDICT_PLAN_FUNDED",
    "build_runway_funding_target",
]
