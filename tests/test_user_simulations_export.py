"""Tests for the pure user simulations export helper."""
from __future__ import annotations

from app.simulation.user_simulations_export import user_simulations_to_csv


def test_user_simulations_to_csv_contains_header_and_rows() -> None:
    csv_text = user_simulations_to_csv(
        [
            {
                "simulation_id": 1,
                "project_id": 10,
                "status": "COMPLETED",
                "created_at": "2026-08-08T06:00:00+00:00",
                "signal_quality": 0.62,
                "product_type": "saas",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "simulation_id,project_id,status,created_at" in csv_text
    assert "1,10,COMPLETED,2026-08-08T06:00:00+00:00,0.62,saas" in csv_text
    assert "generated_at,now" in csv_text
