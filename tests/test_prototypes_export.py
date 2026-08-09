"""Tests for the pure prototypes-export helper."""
from __future__ import annotations

from app.simulation.prototypes_export import prototype_count_to_csv, prototypes_to_csv


def test_prototypes_to_csv_contains_header_and_rows() -> None:
    csv_text = prototypes_to_csv(
        [
            {
                "id": 1,
                "project_id": 10,
                "html_content": "<html></html>",
                "funnel_graph_json": "{\"nodes\": []}",
                "created_at": "2026-08-07T20:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "id,project_id,html_content,funnel_graph_json,created_at" in csv_text
    assert "<html></html>" in csv_text
    assert "generated_at,now" in csv_text


def test_prototypes_to_csv_handles_missing_fields() -> None:
    csv_text = prototypes_to_csv([{"id": 2}])

    assert "2,," in csv_text


def test_prototype_count_to_csv_contains_header_and_row() -> None:
    csv_text = prototype_count_to_csv(
        {"project_id": 10, "prototype_count": 1},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,prototype_count" in csv_text
    assert "10,1" in csv_text
    assert "generated_at,now" in csv_text
