"""Tests for the pure MVP features export helper."""
from __future__ import annotations

from app.simulation.mvp_features_export import features_to_csv


def test_features_to_csv_contains_header_and_rows() -> None:
    csv_text = features_to_csv(
        ["Auth", "Billing"],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "index,feature" in csv_text
    assert "1,Auth" in csv_text
    assert "2,Billing" in csv_text
    assert "generated_at,now" in csv_text


def test_features_to_csv_empty() -> None:
    csv_text = features_to_csv([])

    assert "index,feature" in csv_text
