"""Tests for the pure portfolio prediction-range coverage builder."""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.prediction_range_coverage import (
    PortfolioPredictionRangeCoverageOut,
)
from app.simulation.portfolio_prediction_range_coverage import (
    build_portfolio_prediction_range_coverage,
)


def _row(
    outcome_id: int,
    project_id: int,
    *,
    predicted: float = 0.10,
    actual: float,
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": outcome_id,
        "project_id": project_id,
        "simulation_id": outcome_id,
        "predicted_conversion_rate": predicted,
        "actual_conversion_rate": actual,
        "created_at": created_at,
    }


def _single_project_rows(
    actuals: list[float] | None = None,
) -> list[dict[str, Any]]:
    values = actuals or [0.09, 0.11, 0.09, 0.11, 0.09, 0.11]
    return [
        _row(
            index + 1,
            7,
            actual=value,
            created_at=f"2026-01-{index + 1:02d}T00:00:00+00:00",
        )
        for index, value in enumerate(values)
    ]


def test_empty_rows_produce_zeroed_digest() -> None:
    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=[],
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["user_id"] == 42
    assert payload["generated_at"] == "2026-02-01T00:00:00+00:00"
    assert payload["project_count"] == 0
    assert payload["total_outcomes"] == 0
    assert payload["evaluated_runs"] == 0
    assert payload["coverage_rate"] is None
    assert payload["verdict"] == "INSUFFICIENT_DATA"
    assert payload["projects"] == []
    assert payload["rows"] == []
    assert payload["narrative"].startswith("No founder outcomes")


def test_single_project_matches_per_project_digest() -> None:
    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=_single_project_rows(),
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["project_count"] == 1
    assert payload["total_outcomes"] == 6
    assert payload["evaluated_runs"] == 3
    assert payload["within_range_count"] == 3
    assert payload["coverage_rate"] == pytest.approx(1.0)
    assert payload["verdict"] == "WELL_CALIBRATED"
    assert payload["projects"] == [
        {
            "project_id": 7,
            "total_outcomes": 6,
            "evaluated_runs": 3,
            "within_range_count": 3,
            "coverage_rate": 1.0,
            "verdict": "WELL_CALIBRATED",
        }
    ]
    assert len(payload["rows"]) == 6


def test_two_projects_roll_up_with_user_pool_fallback() -> None:
    rows: list[dict[str, Any]] = []
    actuals = [0.09, 0.11, 0.09, 0.11, 0.09, 0.11]
    for index in range(6):
        created = f"2026-01-{index + 1:02d}T00:00:00+00:00"
        rows.append(
            _row(index * 2 + 1, 7, actual=actuals[index], created_at=created)
        )
        rows.append(
            _row(index * 2 + 2, 9, actual=actuals[index], created_at=created)
        )

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["project_count"] == 2
    assert payload["total_outcomes"] == 12
    assert payload["evaluated_runs"] == 9
    assert payload["within_range_count"] == 9
    assert payload["coverage_rate"] == pytest.approx(1.0)
    assert payload["verdict"] == "WELL_CALIBRATED"
    assert payload["projects"] == [
        {
            "project_id": 7,
            "total_outcomes": 6,
            "evaluated_runs": 4,
            "within_range_count": 4,
            "coverage_rate": 1.0,
            "verdict": "WELL_CALIBRATED",
        },
        {
            "project_id": 9,
            "total_outcomes": 6,
            "evaluated_runs": 5,
            "within_range_count": 5,
            "coverage_rate": 1.0,
            "verdict": "WELL_CALIBRATED",
        },
    ]
    sources = {row["calibration_source"] for row in payload["rows"]}
    assert sources == {"none", "project", "user"}


def test_misses_lower_portfolio_verdict() -> None:
    rows = _single_project_rows([0.09, 0.11, 0.09, 0.11, 0.09, 0.30])

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["evaluated_runs"] == 3
    assert payload["within_range_count"] == 2
    assert payload["coverage_rate"] == pytest.approx(2 / 3)
    assert payload["verdict"] == "NEEDS_ATTENTION"
    assert payload["worst_miss"] is not None
    assert payload["worst_miss"]["simulation_id"] == 6
    assert payload["worst_miss"]["margin"] == pytest.approx(0.18)
    assert any(
        signal["label"] == "coverage_rate"
        and signal["severity"] == "watch"
        for signal in payload["key_signals"]
    )


def test_malformed_rows_are_ignored() -> None:
    rows: list[Any] = [
        _row(1, 7, actual=0.09, created_at="2026-01-01T00:00:00+00:00"),
        {"id": 2, "project_id": 7, "actual_conversion_rate": 0.09},
        {
            "id": 3,
            "project_id": 7,
            "predicted_conversion_rate": "bad",
            "actual_conversion_rate": 0.09,
            "created_at": "2026-01-03T00:00:00+00:00",
        },
        {
            "id": 4,
            "project_id": 7,
            "predicted_conversion_rate": True,
            "actual_conversion_rate": 0.09,
            "created_at": "2026-01-04T00:00:00+00:00",
        },
        {
            "id": 5,
            "project_id": 7,
            "predicted_conversion_rate": float("nan"),
            "actual_conversion_rate": 0.09,
            "created_at": "2026-01-05T00:00:00+00:00",
        },
        {
            "id": 6,
            "project_id": None,
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": 0.09,
            "created_at": "2026-01-06T00:00:00+00:00",
        },
        "not-a-dict",
    ]

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["total_outcomes"] == 1
    assert payload["project_count"] == 1
    assert payload["evaluated_runs"] == 0
    assert payload["verdict"] == "INSUFFICIENT_DATA"


def test_payload_validates_against_portfolio_schema() -> None:
    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=_single_project_rows(),
        generated_at="2026-02-01T00:00:00+00:00",
    )

    validated = PortfolioPredictionRangeCoverageOut.model_validate(payload)
    assert validated.user_id == 42
    assert validated.project_count == 1
    assert validated.verdict == "WELL_CALIBRATED"
    assert validated.rows[0].project_id == 7
    assert validated.projects[0].coverage_rate == pytest.approx(1.0)
