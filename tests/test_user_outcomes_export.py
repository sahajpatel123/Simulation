"""Tests for the pure user outcomes export helper."""
from __future__ import annotations

from app.simulation.user_outcomes_export import user_outcomes_to_csv


def test_user_outcomes_to_csv_contains_header_and_rows() -> None:
    csv_text = user_outcomes_to_csv(
        [
            {
                "outcome_id": 1,
                "project_id": 10,
                "actual_conversion_rate": 0.042,
                "actual_mrr": 1000.0,
                "actual_cac": 50.0,
                "actual_churn_rate": 0.03,
                "created_at": "2026-08-08T07:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "outcome_id,project_id,actual_conversion_rate" in csv_text
    assert "1,10,0.042,1000.0,50.0,0.03" in csv_text
    assert "generated_at,now" in csv_text
