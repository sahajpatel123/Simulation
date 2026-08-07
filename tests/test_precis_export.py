"""Tests for the pure precis-export helper."""
from __future__ import annotations

from app.simulation.precis_export import precis_to_csv


def test_precis_to_csv_contains_header_and_row() -> None:
    csv_text = precis_to_csv(
        {"project_id": 10, "precis": "A lean tool"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,precis" in csv_text
    assert "10,A lean tool" in csv_text
    assert "generated_at,now" in csv_text


def test_precis_to_csv_handles_missing_fields() -> None:
    csv_text = precis_to_csv({"project_id": 10})

    assert "10," in csv_text
