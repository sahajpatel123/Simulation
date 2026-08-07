"""Tests for the pure assumptions-export helper."""
from __future__ import annotations

from app.simulation.assumptions_export import assumptions_to_csv


def test_assumptions_to_csv_contains_header_and_rows() -> None:
    csv_text = assumptions_to_csv(
        [
            {
                "id": 1,
                "project_id": 10,
                "text": "Pricing is critical",
                "category": "pricing",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
                "is_hidden": False,
                "created_at": "2026-08-07T20:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "id,project_id,text,category,sensitivity" in csv_text
    assert "1,10,Pricing is critical,pricing,CRITICAL,9.0,False" in csv_text
    assert "generated_at,now" in csv_text


def test_assumptions_to_csv_handles_missing_fields() -> None:
    csv_text = assumptions_to_csv([{"id": 2}])

    assert "2,,," in csv_text
