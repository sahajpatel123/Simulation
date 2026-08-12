"""Tests for the pure portfolio prediction-range coverage builder."""

from __future__ import annotations

import random
from typing import Any

import pytest

from app.schemas.prediction_range_coverage import (
    PortfolioPredictionRangeCoverageOut,
)
from app.simulation.portfolio_prediction_range_coverage import (
    build_portfolio_prediction_range_coverage,
)
from app.simulation.prediction_range import build_prediction_range
from app.simulation.prediction_range_coverage import (
    _WITHIN_EPSILON,
    MAX_HISTORY_PAIRS,
    MIN_OUTCOMES_FOR_RANGE,
    _choose_history,
    _sort_key,
    _usable_row,
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


def _reference_evaluated_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recompute every out-of-sample check the pre-optimization way.

    Rebuilds both prefix pair lists from ``usable[:index]`` per row, exactly
    like the original quadratic builder, so the incremental path can be
    compared row-for-row against the old selection semantics.
    """
    usable = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("project_id") is not None
        and _usable_row(row) is not None
    ]
    usable.sort(key=_sort_key)

    reference: list[dict[str, Any]] = []
    for index, row in enumerate(usable):
        project_id = int(row["project_id"])
        history, source = _choose_history(
            usable[:index],
            project_id=project_id,
        )
        predicted, actual = _usable_row(row)
        if predicted is None or actual is None:
            continue
        payload = build_prediction_range(
            predicted_conversion_rate=predicted,
            pairs=history,
            simulation_id=int(row.get("simulation_id") or 0),
            project_id=project_id,
            calibration_source=source,
        )
        low = payload.get("low")
        high = payload.get("high")
        history_count = int(payload.get("calibration_sample_count") or 0)
        evaluated = (
            history_count >= MIN_OUTCOMES_FOR_RANGE
            and low is not None
            and high is not None
        )
        within: bool | None = None
        margin: float | None = None
        if evaluated and low is not None and high is not None:
            within = (
                actual >= low - _WITHIN_EPSILON
                and actual <= high + _WITHIN_EPSILON
            )
            if within:
                margin = 0.0
            else:
                margin = min(abs(actual - low), abs(actual - high))
        reference.append(
            {
                "simulation_id": (
                    int(row.get("simulation_id"))
                    if row.get("simulation_id") is not None
                    else None
                ),
                "project_id": project_id,
                "low": low,
                "high": high,
                "history_count": history_count,
                "calibration_source": source,
                "within": within,
                "margin": round(margin, 6) if margin is not None else None,
                "evaluated": bool(evaluated),
            }
        )
    return reference


def test_incremental_history_matches_prefix_rebuild_reference() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(210):
        rows.append(
            _row(
                index + 1,
                7,
                actual=0.09 + (index % 3) * 0.02,
                created_at=(
                    f"2026-01-{min(index % 27 + 1, 28):02d}"
                    "T00:00:00+00:00"
                ),
            )
        )
    for index in range(40):
        rows.append(
            _row(
                1000 + index,
                9,
                actual=0.10 + (index % 3) * 0.01,
                created_at=(
                    f"2026-02-{min(index % 27 + 1, 28):02d}"
                    "T00:00:00+00:00"
                ),
            )
        )
    random.Random(7).shuffle(rows)

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-03-01T00:00:00+00:00",
    )
    reference = _reference_evaluated_rows(rows)

    assert len(payload["rows"]) == len(reference) == 250
    assert payload["project_count"] == 2
    assert payload["evaluated_runs"] == sum(
        1 for row in reference if row["evaluated"]
    )
    for got, expected in zip(payload["rows"], reference, strict=True):
        for key in (
            "simulation_id",
            "project_id",
            "low",
            "high",
            "history_count",
            "calibration_source",
            "within",
            "margin",
            "evaluated",
        ):
            assert got[key] == expected[key], (got, expected)

    sources = {row["calibration_source"] for row in payload["rows"]}
    assert sources == {"none", "user", "project"}
    project_seven = [row for row in payload["rows"] if row["project_id"] == 7]
    assert max(row["history_count"] for row in project_seven) == MAX_HISTORY_PAIRS


def test_large_multi_project_portfolio_rolls_up_correctly() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(1500):
        project_id = (7, 9, 11)[index % 3]
        rows.append(
            _row(
                index + 1,
                project_id,
                actual=0.09 + (index % 5) * 0.01,
                created_at=(
                    f"2026-01-{min(index % 27 + 1, 28):02d}"
                    "T00:00:00+00:00"
                ),
            )
        )

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-02-01T00:00:00+00:00",
    )

    assert payload["project_count"] == 3
    assert payload["total_outcomes"] == 1500
    assert len(payload["rows"]) == 1500
    assert payload["evaluated_runs"] == 1497
    assert payload["verdict"] != "INSUFFICIENT_DATA"
    assert sum(p["total_outcomes"] for p in payload["projects"]) == 1500
    assert sum(p["evaluated_runs"] for p in payload["projects"]) == 1497


def test_malformed_id_and_simulation_id_metadata_are_tolerated() -> None:
    rows = _single_project_rows([0.09, 0.11, 0.09, 0.11, 0.09, 0.11])
    rows.append(
        {
            "id": "not-an-int",
            "project_id": 7,
            "simulation_id": "oops",
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": 0.09,
            "created_at": "2026-02-01T00:00:00+00:00",
        }
    )
    rows.append(
        {
            "id": True,
            "project_id": 7,
            "simulation_id": True,
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": 0.11,
            "created_at": "2026-02-02T00:00:00+00:00",
        }
    )

    payload = build_portfolio_prediction_range_coverage(
        user_id=42,
        rows=rows,
        generated_at="2026-02-03T00:00:00+00:00",
    )

    assert payload["total_outcomes"] == 8
    assert payload["project_count"] == 1
    assert payload["evaluated_runs"] == 5
    assert payload["verdict"] == "WELL_CALIBRATED"
    late_rows = [
        row
        for row in payload["rows"]
        if (row["created_at"] or "").startswith("2026-02-")
    ]
    assert len(late_rows) == 2
    assert all(row["simulation_id"] is None for row in late_rows)


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
