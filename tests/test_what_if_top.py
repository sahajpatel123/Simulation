"""Tests for the top_what_if_scenarios helper."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    build_what_if_scenario,
    top_what_if_scenarios,
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


def _scenario(
    *,
    sim_id: int,
    assumptions: list[dict[str, Any]],
    overrides: dict[str, float] | None = None,
) -> Any:
    return build_what_if_scenario(
        simulation_id=sim_id,
        project_id=sim_id,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=assumptions,
        **(overrides or {}),
    )


def test_top_returns_empty_when_input_empty() -> None:
    assert top_what_if_scenarios([], n=3) == []


def test_top_returns_empty_when_n_is_zero() -> None:
    scenarios = [_scenario(sim_id=1, assumptions=[])]
    assert top_what_if_scenarios(scenarios, n=0) == []


def test_top_returns_n_highest_deltas() -> None:
    scenarios = [
        _scenario(sim_id=1, assumptions=[{
            "text": "Pricing too expensive",
            "sensitivity": "CRITICAL",
            "impact_score": 9,
        }]),
        _scenario(sim_id=2, assumptions=[{
            "text": "Pricing too expensive",
            "sensitivity": "CRITICAL",
            "impact_score": 9,
        }], overrides={"override_price_sensitivity": 0.1}),
        _scenario(sim_id=3, assumptions=[{
            "text": "Reviews missing",
            "sensitivity": "HIGH",
            "impact_score": 7,
        }]),
    ]

    top = top_what_if_scenarios(scenarios, n=2)

    assert len(top) == 2
    assert top[0].rank == 1
    assert top[1].rank == 2
    assert top[0].scenario.conversion_delta >= top[1].scenario.conversion_delta


def test_top_caps_at_input_length() -> None:
    scenarios = [_scenario(sim_id=1, assumptions=[])]
    top = top_what_if_scenarios(scenarios, n=10)
    assert len(top) == 1


def test_top_uses_default_n_three() -> None:
    scenarios = [
        _scenario(sim_id=i, assumptions=[{
            "text": "Pricing",
            "sensitivity": "HIGH",
            "impact_score": 5 + i,
        }])
        for i in range(5)
    ]
    top = top_what_if_scenarios(scenarios)
    assert len(top) == 3
