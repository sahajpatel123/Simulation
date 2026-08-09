"""Tests for the pure competitive-export helper."""
from __future__ import annotations

from app.simulation.competitive_export import (
    competitive_count_to_csv,
    competitors_to_csv,
)


def test_competitors_to_csv_contains_header_and_rows() -> None:
    csv_text = competitors_to_csv(
        [
            {
                "name": "Acme",
                "category": "DIRECT",
                "pricing": "$10/mo",
                "positioning": "premium",
                "target_segment": "SMB",
                "features": ["billing", "reports"],
                "strengths": ["brand"],
                "weaknesses": ["price"],
                "india_presence": "MODERATE",
                "threat_level": "HIGH",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "name,category,pricing,positioning" in csv_text
    assert "Acme,DIRECT,$10/mo,premium" in csv_text
    assert "generated_at,now" in csv_text


def test_competitors_to_csv_handles_missing_fields() -> None:
    csv_text = competitors_to_csv([{"name": "Acme"}])

    assert "Acme," in csv_text


def test_competitive_count_to_csv_contains_header_and_row() -> None:
    csv_text = competitive_count_to_csv(
        {"project_id": 10, "competitive_count": 3},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,competitive_count" in csv_text
    assert "10,3" in csv_text
    assert "generated_at,now" in csv_text
