"""Tests for the scenarios_to_csv batch writer."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import build_what_if_scenario, scenarios_to_csv


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


def test_empty_list_returns_only_header() -> None:
    csv = scenarios_to_csv([])
    header_line = csv.split("\n")[0]
    assert header_line.startswith("simulation_id")
    assert csv.count("\n") == 0


def test_two_scenarios_yield_three_lines() -> None:
    scenarios = [
        build_what_if_scenario(
            simulation_id=1,
            project_id=1,
            base_results=_base(),
            env_params=_env(),
            existing_assumptions=[],
            new_assumptions=[],
        ),
        build_what_if_scenario(
            simulation_id=2,
            project_id=1,
            base_results=_base(),
            env_params=_env(),
            existing_assumptions=[],
            new_assumptions=[],
        ),
    ]

    csv = scenarios_to_csv(scenarios)

    assert csv.count("\n") == 2
    assert csv.split("\n")[0].startswith("simulation_id")
    assert "1" in csv.split("\n")[1]
    assert "2" in csv.split("\n")[2]


def test_csv_header_matches_to_csv_header() -> None:
    scenarios = [
        build_what_if_scenario(
            simulation_id=1,
            project_id=1,
            base_results=_base(),
            env_params=_env(),
            existing_assumptions=[],
            new_assumptions=[],
        ),
    ]

    from app.schemas.what_if import WhatIfOut

    csv = scenarios_to_csv(scenarios)
    header_line = csv.split("\n")[0]
    assert header_line == ",".join(WhatIfOut.to_csv_header())