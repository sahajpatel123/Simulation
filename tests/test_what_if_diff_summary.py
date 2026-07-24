"""Tests for the diff_what_if_scenarios_summary helper."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    build_what_if_scenario,
    diff_what_if_scenarios,
    diff_what_if_scenarios_summary,
)


def _base() -> dict[str, Any]:
    return {
        "population_weighted_conversion": 0.05,
        "conversion_rate": 0.05,
        "mean_revenue": 999.0,
        "product_type_detected": "saas",
    }


def _env() -> dict[str, Any]:
    return {
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }


def _scenario(sim_id: int, assumptions: list[dict[str, Any]]) -> Any:
    return build_what_if_scenario(
        simulation_id=sim_id,
        project_id=sim_id,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=assumptions,
    )


def test_diff_summary_for_shared_pricing_category() -> None:
    base = _scenario(1, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}])
    other = _scenario(2, [{"text": "Pricing again", "sensitivity": "HIGH", "impact_score": 7}])

    diff = diff_what_if_scenarios(base, other)
    line = diff_what_if_scenarios_summary(diff)

    assert "sim=1->2" in line
    assert "delta_diff=" in line
    assert "pricing" in line


def test_diff_summary_shows_none_for_empty_shared_categories() -> None:
    base = _scenario(1, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}])
    other = _scenario(2, [{"text": "UX is confusing", "sensitivity": "HIGH", "impact_score": 7}])

    diff = diff_what_if_scenarios(base, other)
    line = diff_what_if_scenarios_summary(diff)

    assert "[none]" in line


def test_diff_summary_signed_delta_difference() -> None:
    base = _scenario(1, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}])
    other = _scenario(2, [])

    diff = diff_what_if_scenarios(base, other)
    line = diff_what_if_scenarios_summary(diff)

    assert "delta_diff=+" in line or "delta_diff=-" in line