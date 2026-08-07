"""Tests for the pure description-export helper."""
from __future__ import annotations

from app.simulation.description_export import description_to_csv


def test_description_to_csv_contains_header_and_row() -> None:
    csv_text = description_to_csv(
        {"project_id": 10, "description": "A simulation tool"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,description" in csv_text
    assert "10,A simulation tool" in csv_text
    assert "generated_at,now" in csv_text
