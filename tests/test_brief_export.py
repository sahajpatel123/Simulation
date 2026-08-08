"""Tests for the pure founder brief export helper."""
from __future__ import annotations

from app.simulation.brief_export import brief_to_csv


def test_brief_to_csv_contains_header_and_row() -> None:
    csv_text = brief_to_csv(
        {
            "project_id": 10,
            "brief_positioning": "premium saas",
            "brief_features_json": '["billing"]',
            "brief_hook": "save time",
            "brief_completed_at": "2026-08-07T20:00:00+00:00",
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,brief_positioning,brief_features_json" in csv_text
    assert "10,premium saas" in csv_text
    assert "billing" in csv_text
    assert "save time" in csv_text
    assert "generated_at,now" in csv_text


def test_brief_to_csv_handles_missing_fields() -> None:
    csv_text = brief_to_csv({"project_id": 10})

    assert "10,,," in csv_text


def test_brief_positioning_to_csv_contains_header_and_row() -> None:
    from app.simulation.brief_export import brief_positioning_to_csv

    csv_text = brief_positioning_to_csv(
        {"project_id": 10, "brief_positioning": "premium saas"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,brief_positioning" in csv_text
    assert "10,premium saas" in csv_text
    assert "generated_at,now" in csv_text


def test_brief_features_to_csv_contains_header_and_row() -> None:
    from app.simulation.brief_export import brief_features_to_csv

    csv_text = brief_features_to_csv(
        {"project_id": 10, "brief_features_json": '["billing"]'},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,brief_features_json" in csv_text
    assert "billing" in csv_text
    assert "generated_at,now" in csv_text
