"""Tests for the pure title-export helper."""
from __future__ import annotations

from app.simulation.title_export import title_to_csv


def test_title_to_csv_contains_header_and_row() -> None:
    csv_text = title_to_csv(
        {"project_id": 10, "title": "TheCee"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,title" in csv_text
    assert "10,TheCee" in csv_text
    assert "generated_at,now" in csv_text
