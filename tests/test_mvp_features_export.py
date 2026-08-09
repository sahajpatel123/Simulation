"""Tests for the pure MVP features export helper."""
from __future__ import annotations

from app.simulation.mvp_features_export import features_to_csv, mvp_feature_count_to_csv


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


def test_mvp_feature_count_to_csv_contains_header_and_row() -> None:
    csv_text = mvp_feature_count_to_csv(
        {"project_id": 10, "mvp_feature_count": 2},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,mvp_feature_count" in csv_text
    assert "10,2" in csv_text
    assert "generated_at,now" in csv_text
