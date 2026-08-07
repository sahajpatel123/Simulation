"""Tests for the pure quick-stats export helper."""
from __future__ import annotations

from app.simulation.quick_stats_export import quick_stats_to_csv


def test_quick_stats_to_csv_contains_header_and_row() -> None:
    csv_text = quick_stats_to_csv(
        {
            "user_id": 42,
            "total_projects": 2,
            "total_simulations": 3,
            "total_decisions": 4,
            "total_outcomes": 1,
            "account_age_days": 10,
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "user_id,total_projects,total_simulations" in csv_text
    assert "42,2,3,4,1,10" in csv_text
    assert "generated_at,now" in csv_text
