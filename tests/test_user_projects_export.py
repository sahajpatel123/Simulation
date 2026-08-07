"""Tests for the pure user projects export helper."""
from __future__ import annotations

from app.simulation.user_projects_export import user_projects_to_csv


def test_user_projects_to_csv_contains_header_and_rows() -> None:
    csv_text = user_projects_to_csv(
        [
            {
                "project_id": 1,
                "title": "TheCee",
                "status": "DRAFT",
                "intake_mode": "IDEA",
                "is_archived": False,
                "created_at": "2026-08-08T04:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,title,status,intake_mode" in csv_text
    assert "1,TheCee,DRAFT,IDEA,False" in csv_text
    assert "generated_at,now" in csv_text


def test_user_projects_to_csv_empty() -> None:
    csv_text = user_projects_to_csv([])

    assert "project_id,title,status,intake_mode" in csv_text
