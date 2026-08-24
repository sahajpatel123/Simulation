"""Tests for the rank_what_if_scenarios helper."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    RankedWhatIf,
    build_what_if_scenario,
    rank_what_if_scenarios,
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


def test_rank_empty_returns_empty_list() -> None:
    assert rank_what_if_scenarios([]) == []


def test_rank_orders_by_conversion_delta_descending() -> None:
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
    ]

    ranked = rank_what_if_scenarios(scenarios)

    assert isinstance(ranked[0], RankedWhatIf)
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2
    assert ranked[0].scenario.conversion_delta >= ranked[1].scenario.conversion_delta


def test_rank_is_stable_for_ties() -> None:
    scenarios = [
        _scenario(sim_id=1, assumptions=[]),
        _scenario(sim_id=2, assumptions=[]),
    ]

    ranked = rank_what_if_scenarios(scenarios)

    assert [r.scenario.simulation_id for r in ranked] == [1, 2]


def test_rank_single_scenario_gets_rank_one() -> None:
    scenarios = [_scenario(sim_id=42, assumptions=[])]
    ranked = rank_what_if_scenarios(scenarios)

    assert ranked[0].rank == 1
    assert ranked[0].scenario.simulation_id == 42
