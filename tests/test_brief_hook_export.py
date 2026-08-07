"""Tests for the pure brief-hook export helper."""
from __future__ import annotations

from app.simulation.brief_hook_export import brief_hook_to_csv


def test_brief_hook_to_csv_contains_header_and_row() -> None:
    csv_text = brief_hook_to_csv(
        {"project_id": 10, "brief_hook": "save time"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,brief_hook" in csv_text
    assert "10,save time" in csv_text
    assert "generated_at,now" in csv_text
