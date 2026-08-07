"""Tests for the pure is-archived export helper."""
from __future__ import annotations

from app.simulation.is_archived_export import is_archived_to_csv


def test_is_archived_to_csv_contains_header_and_row() -> None:
    csv_text = is_archived_to_csv(
        {"project_id": 10, "is_archived": True},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,is_archived" in csv_text
    assert "10,True" in csv_text
    assert "generated_at,now" in csv_text
