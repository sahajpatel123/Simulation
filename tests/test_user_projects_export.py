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


def test_user_projects_to_csv_neutralizes_formula_injection() -> None:
    csv_text = user_projects_to_csv(
        [
            {
                "project_id": 1,
                "title": "=HYPERLINK(\"http://evil\")",
                "status": "-AT_RISK",
                "intake_mode": "@cmd",
                "is_archived": False,
                "created_at": "2026-08-08T04:00:00+00:00",
            }
        ],
        metadata={
            "generated_at": "=NOW()",
            "user_id": 42,
            "format_version": "1",
        },
    )

    assert "'=HYPERLINK" in csv_text
    assert "'-AT_RISK" in csv_text
    assert "'@cmd" in csv_text
    assert "'=NOW()" in csv_text
    # Non-string cells stay unchanged.
    assert "False" in csv_text


def test_user_projects_to_csv_neutralizes_formula_after_leading_whitespace() -> None:
    csv_text = user_projects_to_csv(
        [
            {
                "project_id": 2,
                "title": " =SUM(1,2)",
                "status": "\t=cmd",
                "intake_mode": "  +1",
                "is_archived": False,
                "created_at": "2026-08-08T04:00:00+00:00",
            }
        ]
    )

    assert "' =SUM(1,2)" in csv_text
    assert "'\t=cmd" in csv_text
    assert "'  +1" in csv_text


def test_user_projects_to_csv_keeps_normal_text_unchanged() -> None:
    csv_text = user_projects_to_csv(
        [
            {
                "project_id": 3,
                "title": "Ordinary idea - not a formula",
                "status": "DRAFT",
                "intake_mode": "IDEA",
                "is_archived": True,
                "created_at": "2026-08-08T04:00:00+00:00",
            }
        ]
    )

    assert "Ordinary idea - not a formula" in csv_text
    assert "'Ordinary" not in csv_text
    assert "True" in csv_text
