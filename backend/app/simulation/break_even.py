"""Pure monthly break-even analysis for completed simulation results.

The simulation supplies expected visitor-to-customer conversion while the
founder supplies a compact operating model. The resulting projection answers
whether current traffic covers fixed costs, what customer and visitor volume
would reach break-even, and how much paid traffic can be afforded per visit.

No database or I/O is performed here; malformed legacy results degrade to an
explicit ``UNREACHABLE`` verdict instead of manufacturing financial upside.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.break_even import BreakEvenOut, BreakEvenVerdict

DEFAULT_MONTHLY_VISITORS: int = 1_000
MIN_MONTHLY_VISITORS: int = 1
MAX_MONTHLY_VISITORS: int = 10_000_000
DEFAULT_MONTHLY_FIXED_COSTS: float = 10_000.0
MAX_MONTHLY_FIXED_COSTS: float = 1_000_000_000.0
DEFAULT_AVERAGE_ORDER_VALUE: float = 100.0
MAX_AVERAGE_ORDER_VALUE: float = 10_000_000.0
DEFAULT_GROSS_MARGIN: float = 0.70
DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH: float = 1.0
MAX_PURCHASES_PER_CUSTOMER_PER_MONTH: float = 1_000.0
DEFAULT_COST_PER_VISITOR: float = 0.0
MAX_COST_PER_VISITOR: float = 1_000_000.0

VERDICT_PROFITABLE: BreakEvenVerdict = "PROFITABLE"
VERDICT_NEAR_BREAK_EVEN: BreakEvenVerdict = "NEAR_BREAK_EVEN"
VERDICT_SHORTFALL: BreakEvenVerdict = "SHORTFALL"
VERDICT_UNREACHABLE: BreakEvenVerdict = "UNREACHABLE"

NEAR_BREAK_EVEN_COVERAGE: float = 0.75


def _safe_float(value: Any, default: float = 0.0) -> float:
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


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_conversion(data: dict[str, Any]) -> tuple[float, str]:
    raw_funnel = data.get("raw_funnel")
    if not isinstance(raw_funnel, dict):
        raw_funnel = {}
    for key in (
        "population_weighted_conversion",
        "mean_conversion_rate",
        "conversion_rate",
    ):
        value = _safe_float(data.get(key))
        if value > 0.0:
            return min(value, 1.0), key
    value = _safe_float(raw_funnel.get("conversion_rate"))
    if value > 0.0:
        return min(value, 1.0), "raw_funnel"
    return 0.0, "none"


def _recommendations(
    *,
    verdict: BreakEvenVerdict,
    conversion: float,
    monthly_fixed_costs: float,
    monthly_operating_result: float,
    contribution_per_visitor: float,
    additional_customers_needed: int | None,
    additional_visitors_needed: int | None,
    safety_margin_ratio: float | None,
    cost_per_visitor: float,
    gross_value_per_visitor: float,
) -> list[str]:
    if conversion <= 0.0:
        return [
            "No usable conversion signal is available; re-run or validate conversion before using this projection."
        ]

    if contribution_per_visitor <= 0.0:
        return [
            f"Each visit currently contributes {contribution_per_visitor:.2f} after acquisition cost; keep cost per visitor below {gross_value_per_visitor:.2f} or improve conversion and margin.",
            "Do not scale paid traffic until every additional visit produces positive contribution.",
        ]

    if verdict == VERDICT_PROFITABLE:
        margin = max(0.0, safety_margin_ratio or 0.0)
        return [
            f"Current traffic clears monthly fixed costs with a {margin:.0%} margin of safety.",
            "Protect contribution per visitor before increasing fixed costs or acquisition spend.",
        ]

    shortfall = abs(min(0.0, monthly_operating_result))
    volume = (
        f"Add about {additional_customers_needed:,} customers from "
        f"{additional_visitors_needed:,} visits per month"
        if additional_customers_needed is not None
        and additional_visitors_needed is not None
        else "Increase positive-contribution customer volume"
    )
    recs = [
        f"{volume} to close the {shortfall:,.2f} monthly operating shortfall.",
    ]
    if cost_per_visitor > 0.0:
        recs.append(
            "Test lower-cost channels because acquisition spend directly raises the traffic required for break-even."
        )
    if monthly_fixed_costs > 0.0:
        recs.append(
            "Validate price, margin, and fixed-cost assumptions before treating the break-even target as a forecast."
        )
    return recs


def build_break_even(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    monthly_fixed_costs: float = DEFAULT_MONTHLY_FIXED_COSTS,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchases_per_customer_per_month: float = (
        DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH
    ),
    cost_per_visitor: float = DEFAULT_COST_PER_VISITOR,
    signal_quality: float | None = None,
) -> BreakEvenOut:
    """Build a deterministic monthly operating break-even projection."""
    data = _coerce_results(results)
    conversion, conversion_source = _extract_conversion(data)
    visitors = max(
        MIN_MONTHLY_VISITORS,
        min(
            MAX_MONTHLY_VISITORS,
            _safe_int(monthly_visitors, DEFAULT_MONTHLY_VISITORS),
        ),
    )
    fixed_costs = _clamp(
        monthly_fixed_costs,
        0.0,
        MAX_MONTHLY_FIXED_COSTS,
        DEFAULT_MONTHLY_FIXED_COSTS,
    )
    aov = _clamp(
        average_order_value,
        0.0,
        MAX_AVERAGE_ORDER_VALUE,
        DEFAULT_AVERAGE_ORDER_VALUE,
    )
    margin = _clamp(gross_margin, 0.0, 1.0, DEFAULT_GROSS_MARGIN)
    purchase_frequency = _clamp(
        purchases_per_customer_per_month,
        0.0,
        MAX_PURCHASES_PER_CUSTOMER_PER_MONTH,
        DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH,
    )
    visitor_cost = _clamp(
        cost_per_visitor,
        0.0,
        MAX_COST_PER_VISITOR,
        DEFAULT_COST_PER_VISITOR,
    )

    monthly_customers = visitors * conversion
    monthly_revenue = monthly_customers * aov * purchase_frequency
    monthly_gross_profit = monthly_revenue * margin
    monthly_acquisition_cost = visitors * visitor_cost
    monthly_contribution = monthly_gross_profit - monthly_acquisition_cost
    monthly_operating_result = monthly_contribution - fixed_costs
    contribution_per_customer = aov * purchase_frequency * margin
    gross_value_per_visitor = conversion * contribution_per_customer
    contribution_per_visitor = gross_value_per_visitor - visitor_cost

    break_even_visitors: int | None = None
    break_even_customers: int | None = None
    additional_visitors_needed: int | None = None
    additional_customers_needed: int | None = None
    safety_margin_ratio: float | None = None
    if contribution_per_visitor > 0.0:
        break_even_visitors = int(math.ceil(fixed_costs / contribution_per_visitor))
        break_even_customers = int(math.ceil(break_even_visitors * conversion))
        additional_visitors_needed = max(0, break_even_visitors - visitors)
        additional_customers_needed = max(
            0,
            int(math.ceil(break_even_customers - monthly_customers)),
        )
        safety_margin_ratio = (visitors - break_even_visitors) / visitors

    maximum_affordable_cost_per_visitor = max(
        0.0,
        gross_value_per_visitor - (fixed_costs / visitors),
    )

    if conversion <= 0.0 or contribution_per_visitor <= 0.0:
        verdict: BreakEvenVerdict = VERDICT_UNREACHABLE
    elif monthly_operating_result >= 0.0:
        verdict = VERDICT_PROFITABLE
    elif fixed_costs > 0.0 and monthly_contribution / fixed_costs >= NEAR_BREAK_EVEN_COVERAGE:
        verdict = VERDICT_NEAR_BREAK_EVEN
    else:
        verdict = VERDICT_SHORTFALL

    recommendations = _recommendations(
        verdict=verdict,
        conversion=conversion,
        monthly_fixed_costs=fixed_costs,
        monthly_operating_result=monthly_operating_result,
        contribution_per_visitor=contribution_per_visitor,
        additional_customers_needed=additional_customers_needed,
        additional_visitors_needed=additional_visitors_needed,
        safety_margin_ratio=safety_margin_ratio,
        cost_per_visitor=visitor_cost,
        gross_value_per_visitor=gross_value_per_visitor,
    )

    return BreakEvenOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        verdict=verdict,
        weighted_conversion_rate=round(conversion, 8),
        monthly_visitors=visitors,
        monthly_fixed_costs=round(fixed_costs, 2),
        average_order_value=round(aov, 2),
        purchases_per_customer_per_month=round(purchase_frequency, 4),
        gross_margin=round(margin, 6),
        cost_per_visitor=round(visitor_cost, 4),
        monthly_customers=round(monthly_customers, 2),
        monthly_revenue=round(monthly_revenue, 2),
        monthly_gross_profit=round(monthly_gross_profit, 2),
        monthly_acquisition_cost=round(monthly_acquisition_cost, 2),
        monthly_contribution=round(monthly_contribution, 2),
        monthly_operating_result=round(monthly_operating_result, 2),
        contribution_per_customer=round(contribution_per_customer, 4),
        contribution_per_visitor=round(contribution_per_visitor, 6),
        break_even_customers=break_even_customers,
        break_even_visitors=break_even_visitors,
        additional_customers_needed=additional_customers_needed,
        additional_visitors_needed=additional_visitors_needed,
        safety_margin_ratio=(
            round(safety_margin_ratio, 6)
            if safety_margin_ratio is not None
            else None
        ),
        maximum_affordable_cost_per_visitor=round(
            maximum_affordable_cost_per_visitor,
            6,
        ),
        recommendations=recommendations,
        meta={
            "conversion_source": conversion_source,
            "signal_quality": (
                round(_safe_float(signal_quality), 6)
                if signal_quality is not None
                else None
            ),
            "model": "linear_monthly_break_even_v1",
        },
    )


__all__ = [
    "DEFAULT_AVERAGE_ORDER_VALUE",
    "DEFAULT_COST_PER_VISITOR",
    "DEFAULT_GROSS_MARGIN",
    "DEFAULT_MONTHLY_FIXED_COSTS",
    "DEFAULT_MONTHLY_VISITORS",
    "DEFAULT_PURCHASES_PER_CUSTOMER_PER_MONTH",
    "MAX_AVERAGE_ORDER_VALUE",
    "MAX_COST_PER_VISITOR",
    "MAX_MONTHLY_FIXED_COSTS",
    "MAX_MONTHLY_VISITORS",
    "MAX_PURCHASES_PER_CUSTOMER_PER_MONTH",
    "MIN_MONTHLY_VISITORS",
    "NEAR_BREAK_EVEN_COVERAGE",
    "VERDICT_NEAR_BREAK_EVEN",
    "VERDICT_PROFITABLE",
    "VERDICT_SHORTFALL",
    "VERDICT_UNREACHABLE",
    "build_break_even",
]
