"""Tests for the pure readiness-score helper."""
from __future__ import annotations

from app.simulation.readiness_score import compute_readiness


def test_compute_readiness_scores_complete_project() -> None:
    result = compute_readiness(
        {
            "title": "TheCee",
            "description": "A simulation engine",
            "tags": ["saas"],
            "simulation_count": 1,
            "decision_count": 1,
            "outcome_count": 1,
        }
    )

    assert result["score"] == 100
    assert result["level"] == "HIGH"
    assert all(check["done"] for check in result["checks"])


def test_compute_readiness_scores_partial_project() -> None:
    result = compute_readiness(
        {
            "title": "TheCee",
            "description": "",
            "tags": [],
            "simulation_count": 0,
            "decision_count": 0,
            "outcome_count": 0,
        }
    )

    assert result["score"] == 10
    assert result["level"] == "LOW"
    assert any(not check["done"] for check in result["checks"])
