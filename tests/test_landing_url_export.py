"""Tests for the pure landing-page-URL export helper."""
from __future__ import annotations

from app.simulation.landing_url_export import landing_url_to_csv


def test_landing_url_to_csv_contains_header_and_row() -> None:
    csv_text = landing_url_to_csv(
        {"project_id": 10, "landing_page_url": "https://example.com"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,landing_page_url" in csv_text
    assert "10,https://example.com" in csv_text
    assert "generated_at,now" in csv_text
