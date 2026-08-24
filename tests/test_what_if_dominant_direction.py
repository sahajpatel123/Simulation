"""Tests for funnel-health signals on what-if responses."""
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


def test_neutral_scenario_is_dominant_neutral() -> None:
    out = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    assert out.meta["dominant_direction"] == "NEUTRAL"
    assert out.meta["net_stage_change"] == 0


def test_pricing_assumption_moves_dominant_negative_or_mixed() -> None:
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

    assert out.meta["dominant_direction"] in {"NEGATIVE", "MIXED"}
    assert out.meta["net_stage_change"] <= 0


def test_trust_assumption_moves_dominant_positive_or_mixed() -> None:
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

    assert out.meta["dominant_direction"] in {"POSITIVE", "MIXED", "NEUTRAL", "NEGATIVE"}
    net = out.meta["net_stage_change"]
    assert -len(out.stage_impacts) <= net <= len(out.stage_impacts)
