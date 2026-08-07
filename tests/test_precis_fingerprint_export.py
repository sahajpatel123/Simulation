"""Tests for the pure precis-fingerprint export helper."""
from __future__ import annotations

from app.simulation.precis_fingerprint_export import precis_fingerprint_to_csv


def test_precis_fingerprint_to_csv_contains_header_and_row() -> None:
    csv_text = precis_fingerprint_to_csv(
        {"project_id": 10, "precis_title_fingerprint": "abc123"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,precis_title_fingerprint" in csv_text
    assert "10,abc123" in csv_text
    assert "generated_at,now" in csv_text
