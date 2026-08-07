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
                "created_at": "2026-08-07T20:00:00+00:00",
                "result": {"winner": "tier_b"},
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "id,project_id,title,status,task_id,created_at,result_json" in csv_text
    assert "1,10,Pricing Tiers,COMPLETED,abc,2026-08-07T20:00:00+00:00" in csv_text
    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "winner" in csv_text
    assert "tier_b" in csv_text


def test_decisions_to_csv_handles_missing_fields() -> None:
    csv_text = decisions_to_csv([{"id": 2}])

    assert "2,,,,," in csv_text
