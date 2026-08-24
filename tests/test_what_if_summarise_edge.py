"""Edge-case tests for summarise_what_if_scenarios."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario, summarise_what_if_scenarios


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


def _scenario(sim_id: int, assumptions: list[dict[str, Any]], overrides: dict[str, float] | None = None) -> Any:
    return build_what_if_scenario(
        simulation_id=sim_id,
        project_id=sim_id,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=assumptions,
        **(overrides or {}),
    )


def test_summary_for_all_pricing_scenarios() -> None:
    scenarios = [
        _scenario(1, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}]),
        _scenario(2, [{"text": "Pricing expensive again", "sensitivity": "HIGH", "impact_score": 7}]),
    ]

    summary = summarise_what_if_scenarios(scenarios)

    categories = {entry.category: entry.count for entry in summary.top_categories}
    assert categories.get("pricing", 0) == 2


def test_summary_aggregates_direction_breakdown_for_mixed_signs() -> None:
    positive = _scenario(1, [], overrides={"override_price_sensitivity": 0.1})
    negative = _scenario(2, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}])

    summary = summarise_what_if_scenarios([positive, negative])

    assert summary.direction_breakdown.get("POSITIVE", 0) >= 1
    assert summary.direction_breakdown.get("NEGATIVE", 0) >= 1


def test_summary_with_single_scenario_has_count_one() -> None:
    scenario = _scenario(1, [])

    summary = summarise_what_if_scenarios([scenario])

    assert summary.scenario_count == 1


def test_summary_top_categories_sorted_descending_by_count() -> None:
    scenarios = [
        _scenario(1, [
            {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
        ]),
        _scenario(2, [
            {"text": "Pricing again", "sensitivity": "HIGH", "impact_score": 7},
        ]),
        _scenario(3, [
            {"text": "UX is confusing", "sensitivity": "MEDIUM", "impact_score": 5},
        ]),
    ]

    summary = summarise_what_if_scenarios(scenarios)

    counts = [entry.count for entry in summary.top_categories]
    assert counts == sorted(counts, reverse=True)
    assert summary.top_categories[0].category == "pricing"
