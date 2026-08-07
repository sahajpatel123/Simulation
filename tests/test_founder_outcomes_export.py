"""Tests for the pure founder-outcomes export helper."""
from __future__ import annotations

import json

from app.simulation.founder_outcomes_export import (
    founder_outcomes_to_csv,
    predicted_conversion_from_results,
)


def _row() -> dict:
    return {
        "id": 1,
        "simulation_id": 7,
        "project_id": 10,
        "project_title": "Lean tool",
        "created_at": "2026-08-07T20:00:00+00:00",
        "launched": True,
        "actual_conversion_rate": 0.05,
        "predicted_conversion_rate": 0.04,
        "signal_quality_at_run": 0.62,
        "days_since_launch": 30,
        "data_confidence": "ESTIMATED",
        "product_changed_since_sim": False,
        "pricing_changed": True,
        "target_market_changed": False,
        "validated": True,
        "learning_weight": 0.8,
        "notes": "launched in beta",
    }


def test_founder_outcomes_to_csv_contains_header_and_gap() -> None:
    csv_text = founder_outcomes_to_csv(
        [_row()],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,1" in csv_text
    assert "id,simulation_id,project_id,project_title,created_at,launched" in csv_text
    assert (
        "1,7,10,Lean tool,2026-08-07T20:00:00+00:00,true,0.05,0.04,25.0,"
        "0.62,30,ESTIMATED,false,true,false,true,0.8,launched in beta"
    ) in csv_text


def test_founder_outcomes_to_csv_handles_empty_rows() -> None:
    csv_text = founder_outcomes_to_csv([])

    assert "id,simulation_id,project_id,project_title" in csv_text
    assert "1,7,10" not in csv_text


def test_founder_outcomes_to_csv_handles_missing_fields() -> None:
    csv_text = founder_outcomes_to_csv(
        [
            {
                "id": 2,
                "simulation_id": 8,
                "project_id": 11,
                "actual_conversion_rate": 0.03,
                "predicted_conversion_rate": None,
            }
        ]
    )

    assert "2,8,11" in csv_text
    assert ",0.03," in csv_text


def test_predicted_conversion_from_results_handles_payload_shapes() -> None:
    assert predicted_conversion_from_results(
        {"population_weighted_conversion": 0.04}
    ) == 0.04
    assert predicted_conversion_from_results(
        json.dumps({"conversion_rate": 0.03})
    ) == 0.03
    assert predicted_conversion_from_results({"mean_conversion_rate": 0.02}) == 0.02
    assert predicted_conversion_from_results({}) is None
    assert predicted_conversion_from_results(None) is None
    assert predicted_conversion_from_results("not json") is None
