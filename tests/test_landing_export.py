"""Tests for the pure landing-page export helper."""
from __future__ import annotations

from app.simulation.landing_export import landing_to_csv


def test_landing_to_csv_contains_header_and_row() -> None:
    csv_text = landing_to_csv(
        {
            "project_id": 10,
            "landing_page_url": "https://example.com",
            "existing_product_description": "A lean tool",
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,landing_page_url,existing_product_description" in csv_text
    assert "10,https://example.com,A lean tool" in csv_text
    assert "generated_at,now" in csv_text


def test_landing_to_csv_handles_missing_fields() -> None:
    csv_text = landing_to_csv({"project_id": 10})

    assert "10,," in csv_text
