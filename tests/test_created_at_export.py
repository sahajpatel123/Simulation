"""Tests for the pure created-at export helper."""
from __future__ import annotations

from app.simulation.created_at_export import created_at_to_csv


def test_created_at_to_csv_contains_header_and_row() -> None:
    csv_text = created_at_to_csv(
        {"project_id": 10, "created_at": "2026-08-08T05:00:00+00:00"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,created_at" in csv_text
    assert "10,2026-08-08T05:00:00+00:00" in csv_text
    assert "generated_at,now" in csv_text
