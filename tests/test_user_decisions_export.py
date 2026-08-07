"""Tests for the pure user decisions export helper."""
from __future__ import annotations

from app.simulation.user_decisions_export import user_decisions_to_csv


def test_user_decisions_to_csv_contains_header_and_rows() -> None:
    csv_text = user_decisions_to_csv(
        [
            {
                "decision_id": 1,
                "project_id": 10,
                "title": "Pricing",
                "status": "COMPLETED",
                "created_at": "2026-08-08T07:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "decision_id,project_id,title,status" in csv_text
    assert "1,10,Pricing,COMPLETED,2026-08-08T07:00:00+00:00" in csv_text
    assert "generated_at,now" in csv_text
