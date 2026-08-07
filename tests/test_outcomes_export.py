"""Tests for the pure outcomes-export helper."""
from __future__ import annotations

from app.simulation.outcomes_export import outcomes_to_csv


def test_outcomes_to_csv_contains_header_and_rows() -> None:
    csv_text = outcomes_to_csv(
        [
            {
                "id": 1,
                "project_id": 10,
                "simulation_id": 7,
                "created_at": "2026-08-07T20:00:00+00:00",
                "actual_conversion_rate": 0.042,
                "actual_mrr": 1000.0,
                "actual_cac": 50.0,
                "actual_churn_rate": 0.03,
                "actual_dau": 120,
                "actual_nps": 42.0,
                "days_since_launch": 30,
                "notes": "launch",
                "predicted_conversion_rate": 0.04,
                "predicted_mrr": 900.0,
                "predicted_revenue": 950.0,
                "variance_conversion": 0.002,
                "variance_mrr": 100.0,
                "variance_cac": -5.0,
                "variance_churn": 0.01,
                "calibration_score": 0.82,
            }
        ]
    )

    assert "id,project_id,simulation_id,created_at" in csv_text
    assert "1,10,7,2026-08-07T20:00:00+00:00,0.042" in csv_text
    assert "launch" in csv_text


def test_outcomes_to_csv_handles_missing_fields() -> None:
    csv_text = outcomes_to_csv([{"id": 2}])

    assert "2," in csv_text
