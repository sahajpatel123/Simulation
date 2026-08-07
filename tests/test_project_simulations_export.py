"""Tests for the pure project-simulations export helper."""
from __future__ import annotations

from app.simulation.project_simulations_export import simulations_to_csv


def test_simulations_to_csv_contains_header_and_rows() -> None:
    csv_text = simulations_to_csv(
        [
            {
                "simulation_id": 1,
                "project_id": 10,
                "status": "COMPLETED",
                "created_at": "2026-08-07T20:00:00+00:00",
                "signal_quality": 0.62,
                "product_type": "saas",
                "population_weighted_conversion": 0.042,
            }
        ]
    )

    assert "simulation_id,project_id,status,created_at" in csv_text
    assert "1,10,COMPLETED,2026-08-07T20:00:00+00:00,0.6200,saas,0.0420" in csv_text


def test_simulations_to_csv_handles_missing_fields() -> None:
    csv_text = simulations_to_csv([{"simulation_id": 2}])

    assert "2,,," in csv_text
