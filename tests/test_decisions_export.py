"""Tests for the pure decisions-export helper."""
from __future__ import annotations

from app.simulation.decisions_export import decisions_to_csv


def test_decisions_to_csv_contains_header_and_rows() -> None:
    csv_text = decisions_to_csv(
        [
            {
                "id": 1,
                "project_id": 10,
                "title": "Pricing Tiers",
                "status": "COMPLETED",
                "task_id": "abc",
                "result": {"winner": "tier_b"},
            }
        ]
    )

    assert "id,project_id,title,status,task_id,result_json" in csv_text
    assert "1,10,Pricing Tiers,COMPLETED,abc" in csv_text
    assert "winner" in csv_text
    assert "tier_b" in csv_text


def test_decisions_to_csv_handles_missing_fields() -> None:
    csv_text = decisions_to_csv([{"id": 2}])

    assert "2,,,,," in csv_text
