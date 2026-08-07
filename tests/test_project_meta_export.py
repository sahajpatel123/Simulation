"""Tests for the pure project metadata export helper."""
from __future__ import annotations

from app.simulation.project_meta_export import project_meta_to_csv


def test_project_meta_to_csv_contains_header_and_row() -> None:
    csv_text = project_meta_to_csv(
        {
            "project_id": 10,
            "title": "TheCee",
            "description": "A simulation tool",
            "status": "DRAFT",
            "intake_mode": "IDEA",
            "is_archived": False,
            "created_at": "2026-08-08T04:00:00+00:00",
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,title,description,status" in csv_text
    assert "10,TheCee,A simulation tool,DRAFT,IDEA,False" in csv_text
    assert "generated_at,now" in csv_text


def test_project_meta_to_csv_handles_missing_fields() -> None:
    csv_text = project_meta_to_csv({"project_id": 10})

    assert "10,,," in csv_text
