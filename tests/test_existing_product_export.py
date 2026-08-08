"""Tests for the pure existing-product export helper."""
from __future__ import annotations

from app.simulation.existing_product_export import existing_product_to_csv


def test_existing_product_to_csv_contains_header_and_row() -> None:
    csv_text = existing_product_to_csv(
        {"project_id": 10, "existing_product_description": "A lean tool"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,existing_product_description" in csv_text
    assert "10,A lean tool" in csv_text
    assert "generated_at,now" in csv_text


def test_existing_product_to_csv_neutralizes_formula_injection() -> None:
    csv_text = existing_product_to_csv(
        {"project_id": 10, "existing_product_description": "=HYPERLINK(\"http://evil\")"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "'=HYPERLINK" in csv_text
