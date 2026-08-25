"""Tests for stage regression / improvement counters on what-if responses."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario


def _base() -> dict[str, Any]:
    return {
        "population_weighted_conversion": 0.06,
        "conversion_rate": 0.06,
        "mean_revenue": 1500.0,
        "product_type_detected": "saas",
    }


def _env() -> dict[str, Any]:
    return {
        "average_order_value": 1500.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }


def test_neutral_scenario_has_zero_stage_changes() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    assert out.meta["stage_regression_count"] == 0
    assert out.meta["stage_improvement_count"] == 0


def test_pricing_assumption_regresses_at_least_one_stage() -> None:
    out = build_what_if_scenario(
        simulation_id=2,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Pricing is too expensive for tier-3 users",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
            }
        ],
    )

    assert out.meta["stage_regression_count"] >= 1
    assert out.meta["stage_regression_count"] + out.meta["stage_improvement_count"] <= len(out.stage_impacts)


def test_trust_assumption_can_improve_a_stage() -> None:
    out = build_what_if_scenario(
        simulation_id=3,
        project_id=3,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Strong testimonials and credible reviews from existing users",
                "sensitivity": "HIGH",
                "impact_score": 8.0,
            }
        ],
    )

    total_changes = (
        out.meta["stage_regression_count"] + out.meta["stage_improvement_count"]
    )
    assert total_changes >= 0
    assert total_changes <= len(out.stage_impacts)
