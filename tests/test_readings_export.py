"""Tests for the pure readings-export helper."""
from __future__ import annotations

from app.simulation.readings_export import readings_to_csv


def test_readings_to_csv_contains_header_and_row() -> None:
    csv_text = readings_to_csv(
        {"project_id": 10, "readings_json": "{\"a\": 1}"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,readings_json" in csv_text
    assert "10," in csv_text
    assert "generated_at,now" in csv_text


def test_readings_to_csv_handles_missing_fields() -> None:
    csv_text = readings_to_csv({"project_id": 10})

    assert "10," in csv_text
