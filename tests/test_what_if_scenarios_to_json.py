"""Tests for the scenarios_to_json batch writer."""
from __future__ import annotations

import json
from typing import Any

from app.simulation.what_if import build_what_if_scenario, scenarios_to_json


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


def test_empty_list_yields_empty_array() -> None:
    out = scenarios_to_json([])
    assert json.loads(out) == []


def test_one_scenario_serialises_to_summary() -> None:
    scenario = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    out = scenarios_to_json([scenario])
    parsed = json.loads(out)

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["simulation_id"] == 1
    assert parsed[0]["base_conversion_rate"] == scenario.base_conversion_rate


def test_two_scenarios_serialise_in_order() -> None:
    a = build_what_if_scenario(
        simulation_id=1, project_id=1, base_results=_base(),
        env_params=_env(), existing_assumptions=[], new_assumptions=[],
    )
    b = build_what_if_scenario(
        simulation_id=2, project_id=1, base_results=_base(),
        env_params=_env(), existing_assumptions=[], new_assumptions=[],
    )

    parsed = json.loads(scenarios_to_json([a, b]))

    assert [item["simulation_id"] for item in parsed] == [1, 2]