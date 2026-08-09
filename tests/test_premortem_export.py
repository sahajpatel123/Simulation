"""Tests for the pure premortem-export helper."""
from __future__ import annotations

from app.simulation.premortem_export import premortem_count_to_csv, premortem_to_csv


def test_premortem_to_csv_contains_header_and_rows() -> None:
    csv_text = premortem_to_csv(
        [
            {
                "title": "Price too low",
                "probability": 0.7,
                "severity": "CRITICAL",
                "trigger_condition": "Users don't pay",
                "linked_assumption_texts": ["willing to pay"],
                "intervention": "Test pricing",
                "intervention_impact": "High",
                "earliest_signal": "low conversion",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "title,probability,severity,trigger_condition" in csv_text
    assert "Price too low" in csv_text
    assert "generated_at,now" in csv_text


def test_premortem_to_csv_handles_missing_fields() -> None:
    csv_text = premortem_to_csv([{"title": "x"}])

    assert "x," in csv_text


def test_premortem_count_to_csv_contains_header_and_row() -> None:
    csv_text = premortem_count_to_csv(
        {"project_id": 10, "premortem_count": 1},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,premortem_count" in csv_text
    assert "10,1" in csv_text
    assert "generated_at,now" in csv_text
