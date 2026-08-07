"""Tests for the pure intake-mode export helper."""
from __future__ import annotations

from app.simulation.intake_mode_export import intake_mode_to_csv


def test_intake_mode_to_csv_contains_header_and_row() -> None:
    csv_text = intake_mode_to_csv(
        {"project_id": 10, "intake_mode": "IDEA"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,intake_mode" in csv_text
    assert "10,IDEA" in csv_text
    assert "generated_at,now" in csv_text
