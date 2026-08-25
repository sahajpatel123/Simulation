"""Edge-case tests for diff_what_if_scenarios."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario, diff_what_if_scenarios


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


def test_diff_self_pair_has_zero_delta_difference() -> None:
    scenario = _scenario(1, [{"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9}])

    diff = diff_what_if_scenarios(scenario, scenario)

    assert diff.delta_difference == 0.0
    assert diff.base_delta == diff.other_delta


def test_diff_self_pair_full_category_overlap() -> None:
    scenario = _scenario(
        1,
        [
            {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
            {"text": "UX is confusing", "sensitivity": "HIGH", "impact_score": 7},
        ],
    )

    diff = diff_what_if_scenarios(scenario, scenario)

    assert diff.base_only_categories == []
    assert diff.other_only_categories == []
    assert set(diff.shared_keyword_categories) == {"pricing", "ux"}


def test_diff_categories_remain_sorted_across_inputs() -> None:
    a = _scenario(1, [
        {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
        {"text": "Trust missing", "sensitivity": "HIGH", "impact_score": 7},
    ])
    b = _scenario(2, [
        {"text": "Pricing too expensive", "sensitivity": "HIGH", "impact_score": 7},
        {"text": "UX is confusing", "sensitivity": "MEDIUM", "impact_score": 5},
    ])

    diff = diff_what_if_scenarios(a, b)

    assert diff.shared_keyword_categories == sorted(diff.shared_keyword_categories)
    assert diff.base_only_categories == sorted(diff.base_only_categories)
    assert diff.other_only_categories == sorted(diff.other_only_categories)
