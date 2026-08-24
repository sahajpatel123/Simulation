"""Tests that the what-if export surfaces agree on the same meta values."""
from __future__ import annotations

from typing import Any

from app.simulation.what_if import (
    build_what_if_scenario,
    scenarios_to_csv,
    scenarios_to_json,
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


def _scenario() -> Any:
    return build_what_if_scenario(
        simulation_id=1,
        project_id=2,
        base_results=_base(),
        env_params=_env(),
        existing_assumptions=[],
        new_assumptions=[
            {"text": "Pricing too expensive", "sensitivity": "CRITICAL", "impact_score": 9},
        ],
    )


def test_summary_matches_csv_row_for_same_scenario() -> None:
    scenario = _scenario()
    summary = scenario.summary()
    csv = scenarios_to_csv([scenario])
    csv_data_row = csv.split("\n")[1]

    assert str(summary["simulation_id"]) in csv_data_row
    assert str(summary["project_id"]) in csv_data_row
    assert summary["dominant_direction"] in csv_data_row
    assert summary["sensitivity_label"] in csv_data_row
    assert "pricing" in csv_data_row


def test_summary_matches_json_array_for_same_scenario() -> None:
    scenario = _scenario()
    summary = scenario.summary()
    parsed = __import__("json").loads(scenarios_to_json([scenario]))

    assert parsed[0]["simulation_id"] == summary["simulation_id"]
    assert parsed[0]["dominant_direction"] == summary["dominant_direction"]
    assert parsed[0]["sensitivity_label"] == summary["sensitivity_label"]
    assert parsed[0]["matched_keyword_categories"] == summary["matched_keyword_categories"]


def test_summary_matches_markdown_table_for_same_scenario() -> None:
    scenario = _scenario()
    summary = scenario.summary()
    md = scenarios_to_markdown_table([scenario])

    assert "pricing" in md
    assert summary["dominant_direction"] in md
    assert summary["sensitivity_label"] in md


def test_log_line_includes_direction_matching_summary() -> None:
    scenario = _scenario()

    assert scenario.summary()["dominant_direction"] in scenario.to_log_line()
