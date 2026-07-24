"""Tests for the scenarios_to_markdown_table helper."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    build_what_if_scenario,
    scenarios_to_markdown_table,
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


def test_empty_list_returns_empty_string() -> None:
    assert scenarios_to_markdown_table([]) == ""


def test_single_scenario_yields_three_lines() -> None:
    scenario = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    md = scenarios_to_markdown_table([scenario])

    lines = md.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("| simulation_id |")
    assert lines[1].startswith("| ---")
    assert "1" in lines[2]


def test_multiple_scenarios_comma_separate_categories() -> None:
    a = build_what_if_scenario(
        simulation_id=1,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
            {"text": "UX is confusing", "sensitivity": "HIGH", "impact_score": 7},
        ],
    )
    b = build_what_if_scenario(
        simulation_id=2,
        project_id=1,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[],
    )

    md = scenarios_to_markdown_table([a, b])

    assert md.count("\n") == 3  # header + separator + 2 rows
    assert "pricing, ux" in md
    assert "1" in md.split("\n")[2]
    assert "2" in md.split("\n")[3]