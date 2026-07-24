"""Tests for the scenarios_to_compact_lines helper."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    build_what_if_scenario,
    scenarios_to_compact_lines,
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


def _scenario(sim_id: int, assumptions: list[dict[str, Any]] | None = None) -> Any:
    return build_what_if_scenario(
        simulation_id=sim_id,
        project_id=sim_id,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=assumptions or [],
    )


def test_empty_input_returns_empty_string() -> None:
    assert scenarios_to_compact_lines([]) == ""


def test_single_scenario_yields_one_line() -> None:
    scenario = _scenario(1)

    text = scenarios_to_compact_lines([scenario])

    assert text == scenario.to_log_line()
    assert "\n" not in text


def test_two_scenarios_yield_two_lines() -> None:
    a = _scenario(1)
    b = _scenario(2)

    text = scenarios_to_compact_lines([a, b])

    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0] == a.to_log_line()
    assert lines[1] == b.to_log_line()