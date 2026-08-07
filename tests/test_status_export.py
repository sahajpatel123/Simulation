"""Tests for the pure status-export helper."""
from __future__ import annotations

from app.simulation.status_export import status_to_csv


def test_status_to_csv_contains_header_and_row() -> None:
    csv_text = status_to_csv(
        {"project_id": 10, "status": "DRAFT"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,status" in csv_text
    assert "10,DRAFT" in csv_text
    assert "generated_at,now" in csv_text
