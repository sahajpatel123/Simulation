"""Tests for the pure dossier-axis export helper."""
from __future__ import annotations

from app.simulation.dossier_axis_export import dossier_axis_to_csv


def test_dossier_axis_to_csv_contains_header_and_row() -> None:
    csv_text = dossier_axis_to_csv(
        {"project_id": 10, "dossier_axis": "software"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,dossier_axis" in csv_text
    assert "10,software" in csv_text
    assert "generated_at,now" in csv_text


def test_dossier_axis_to_csv_handles_none_value() -> None:
    csv_text = dossier_axis_to_csv({"project_id": 10, "dossier_axis": None})

    assert "project_id,dossier_axis" in csv_text
    assert "10,\n" in csv_text or csv_text.rstrip().endswith("10,")
