"""Tests for the pure tags-export helper."""
from __future__ import annotations

from app.simulation.tags_export import tag_count_to_csv, tags_to_csv


def test_tags_to_csv_contains_header_and_rows() -> None:
    csv_text = tags_to_csv(
        ["saas", "india"],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "index,tag" in csv_text
    assert "1,saas" in csv_text
    assert "2,india" in csv_text
    assert "generated_at,now" in csv_text


def test_tags_to_csv_empty() -> None:
    csv_text = tags_to_csv([])

    assert "index,tag" in csv_text


def test_tag_count_to_csv_contains_header_and_row() -> None:
    csv_text = tag_count_to_csv(
        {"project_id": 10, "tag_count": 2},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,tag_count" in csv_text
    assert "10,2" in csv_text
    assert "generated_at,now" in csv_text
