"""Tests for the pure interventions-export helper."""
from __future__ import annotations

from app.simulation.interventions_export import (
    intervention_count_to_csv,
    interventions_to_csv,
)


def test_interventions_to_csv_contains_header_and_rows() -> None:
    csv_text = interventions_to_csv(
        [
            {
                "list_type": "interventions",
                "id": "i1",
                "title": "Run pricing test",
                "description": "Test different price points",
                "expected_impact": "High",
                "difficulty": "MEDIUM",
                "estimated_cost": "$500",
                "linked_assumption": "willing to pay",
                "linked_failure_mode": "price too low",
                "priority_score": 0.9,
                "time_to_implement": "2 weeks",
                "success_metric": "conversion",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "list_type,id,title,description" in csv_text
    assert "interventions,i1,Run pricing test" in csv_text
    assert "generated_at,now" in csv_text


def test_interventions_to_csv_handles_missing_fields() -> None:
    csv_text = interventions_to_csv([{"id": "x"}])

    assert ",x," in csv_text


def test_intervention_count_to_csv_contains_header_and_row() -> None:
    csv_text = intervention_count_to_csv(
        {"project_id": 10, "intervention_count": 2},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,intervention_count" in csv_text
    assert "10,2" in csv_text
    assert "generated_at,now" in csv_text
