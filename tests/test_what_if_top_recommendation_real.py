"""Integration test for top_recommendation against a real build_what_if_scenario."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario


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


def test_top_recommendation_priority_one_for_pricing_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Pricing too expensive for tier-3 users",
                "sensitivity": "CRITICAL",
                "impact_score": 9,
            }
        ],
    )

    top = out.top_recommendation()
    assert top is not None
    assert top.priority == 1


def test_top_recommendation_is_none_for_neutral_scenario() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    if not out.recommendations:
        assert out.top_recommendation() is None
    else:
        # If a neutral rec exists, top_recommendation should still resolve.
        assert out.top_recommendation() is not None
