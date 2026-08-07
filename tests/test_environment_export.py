"""Tests for the pure environment-export helper."""
from __future__ import annotations

from app.simulation.environment_export import environment_to_csv


def test_environment_to_csv_contains_header_and_row() -> None:
    csv_text = environment_to_csv(
        {
            "environment_id": 1,
            "project_id": 10,
            "mode": "MANUAL",
            "consumer_volume": 10000,
            "growth_rate_per_month": 5.0,
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
            "scenario_type": None,
            "manual_params_json": {"a": 1},
            "trend_data_json": None,
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "environment_id,project_id,mode,consumer_volume" in csv_text
    assert "1,10,MANUAL,10000,5.0,999.0,0.5,0.3" in csv_text
    assert "generated_at,now" in csv_text


def test_environment_to_csv_handles_missing_fields() -> None:
    csv_text = environment_to_csv({"project_id": 10})

    assert "10," in csv_text
