"""Tests for the out-of-sample prediction-range coverage digest.

Covers the pure builder in ``app.simulation.prediction_range_coverage``:
row evaluation, history-source fallback, coverage aggregates, verdicts,
narratives, malformed-input tolerance and the Pydantic contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.prediction_range_coverage import (
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_NEEDS_ATTENTION,
    VERDICT_POORLY_CALIBRATED,
    VERDICT_WELL_CALIBRATED,
    PredictionRangeCoverageOut,
)
from app.simulation.prediction_range_coverage import (
    MAX_HISTORY_PAIRS,
    MIN_EVALUATED_FOR_VERDICT,
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range_coverage,
)


def _row(
    *,
    row_id: int,
    project_id: int,
    predicted: float = 0.10,
    actual: float = 0.10,
    simulation_id: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "project_id": project_id,
        "simulation_id": simulation_id if simulation_id is not None else row_id,
        "predicted_conversion_rate": predicted,
        "actual_conversion_rate": actual,
        "created_at": created_at or f"2026-01-{row_id:02d}T00:00:00+00:00",
    }


def _target_rows(
    actuals: list[float],
    *,
    predicted: float = 0.10,
    project_id: int = 7,
    start_id: int = 1,
) -> list[dict[str, Any]]:
    return [
        _row(
            row_id=start_id + index,
            project_id=project_id,
            predicted=predicted,
            actual=actual,
        )
        for index, actual in enumerate(actuals)
    ]


def test_empty_rows_produce_zeroed_insufficient_digest() -> None:
    payload = build_prediction_range_coverage(project_id=7, rows=[])

    assert payload["project_id"] == 7
    assert payload["total_project_outcomes"] == 0
    assert payload["evaluated_runs"] == 0
    assert payload["within_range_count"] == 0
    assert payload["coverage_rate"] is None
    assert payload["mean_margin"] is None
    assert payload["worst_miss"] is None
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert payload["rows"] == []
    assert "No founder outcomes" in payload["narrative"]


def test_rows_without_enough_history_are_not_evaluated() -> None:
    rows = _target_rows([0.09, 0.11, 0.09])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["total_project_outcomes"] == 3
    assert payload["evaluated_runs"] == 0
    assert all(row["evaluated"] is False for row in payload["rows"])
    assert all(
        row["history_count"] < MIN_OUTCOMES_FOR_RANGE
        for row in payload["rows"]
    )
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert "enough earlier calibration history" in payload["narrative"]


def test_well_calibrated_band_verdict_and_coverage() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.11, 0.09, 0.11])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["total_project_outcomes"] == 6
    assert payload["evaluated_runs"] == 3
    assert payload["within_range_count"] == 3
    assert payload["coverage_rate"] == pytest.approx(1.0)
    assert payload["mean_margin"] is None
    assert payload["verdict"] == VERDICT_WELL_CALIBRATED
    assert payload["worst_miss"] is None
    assert all(
        row["evaluated"] is True
        for row in payload["rows"]
        if row["history_count"] >= MIN_OUTCOMES_FOR_RANGE
    )
    assert "well calibrated" in payload["narrative"]


def test_misses_drive_needs_attention_and_worst_miss() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.40, 0.09, 0.11])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["evaluated_runs"] == 3
    assert payload["within_range_count"] == 2
    assert payload["coverage_rate"] == pytest.approx(2 / 3)
    assert payload["verdict"] == VERDICT_NEEDS_ATTENTION
    assert payload["worst_miss"] is not None
    assert payload["worst_miss"]["simulation_id"] == 4
    assert payload["worst_miss"]["margin"] > 0.0
    assert "miss too often" in payload["narrative"]


def test_repeated_misses_produce_poorly_calibrated_verdict() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.50, 0.05, 0.55])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["evaluated_runs"] == 3
    assert payload["within_range_count"] == 1
    assert payload["verdict"] == VERDICT_POORLY_CALIBRATED
    assert payload["coverage_rate"] == pytest.approx(1 / 3)
    assert payload["worst_miss"] is not None
    assert "rarely contained" in payload["narrative"]


def test_fewer_than_minimum_evaluated_rows_stays_insufficient() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.10])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["evaluated_runs"] == 1
    assert payload["evaluated_runs"] < MIN_EVALUATED_FOR_VERDICT
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert "Only 1 run(s) could be evaluated" in payload["narrative"]


def test_user_pool_fallback_calibrates_young_project() -> None:
    user_rows = _target_rows(
        [0.09, 0.11, 0.09],
        project_id=99,
        start_id=1,
    )
    target_row = _row(
        row_id=4,
        project_id=7,
        predicted=0.10,
        actual=0.11,
    )
    rows = user_rows + [target_row]
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["total_project_outcomes"] == 1
    assert payload["evaluated_runs"] == 1
    evaluated = payload["rows"][0]
    assert evaluated["evaluated"] is True
    assert evaluated["calibration_source"] == "user"
    assert evaluated["history_count"] == 3


def test_project_history_preferred_over_user_pool() -> None:
    user_rows = _target_rows(
        [0.09, 0.11, 0.09],
        project_id=99,
        start_id=1,
    )
    project_rows = _target_rows(
        [0.09, 0.11, 0.09, 0.11],
        project_id=7,
        start_id=4,
    )
    rows = user_rows + project_rows
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    evaluated = [row for row in payload["rows"] if row["evaluated"]]
    assert len(evaluated) == 4
    project_sourced = [
        row for row in evaluated if row["calibration_source"] == "project"
    ]
    assert len(project_sourced) == 1
    assert project_sourced[0]["history_count"] == 3


def test_history_is_capped_to_live_endpoint_limit() -> None:
    """The rebuild uses the same 200-pair budget as the live endpoint."""
    from app.simulation.prediction_range import build_prediction_range

    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        _row(
            row_id=index + 1,
            project_id=7,
            predicted=0.10,
            actual=0.90,
            created_at=base + timedelta(days=index),
        )
        for index in range(5)
    ]
    rows.extend(
        _row(
            row_id=index + 6,
            project_id=7,
            predicted=0.10,
            actual=0.09 if index % 2 == 0 else 0.11,
            created_at=base + timedelta(days=index + 5),
        )
        for index in range(MAX_HISTORY_PAIRS)
    )
    target = _row(
        row_id=MAX_HISTORY_PAIRS + 6,
        project_id=7,
        predicted=0.10,
        actual=0.10,
        created_at=base + timedelta(days=MAX_HISTORY_PAIRS + 5),
    )

    payload = build_prediction_range_coverage(
        project_id=7,
        rows=[*rows, target],
    )
    evaluated = [row for row in payload["rows"] if row["evaluated"]]
    target_row = next(
        row
        for row in evaluated
        if row["simulation_id"] == target["simulation_id"]
    )
    assert target_row["history_count"] == MAX_HISTORY_PAIRS
    assert target_row["calibration_source"] == "project"

    recent_pairs = [
        (row["predicted_conversion_rate"], row["actual_conversion_rate"])
        for row in rows[-MAX_HISTORY_PAIRS:]
    ]
    expected = build_prediction_range(
        predicted_conversion_rate=0.10,
        pairs=recent_pairs,
        simulation_id=target["simulation_id"],
        project_id=7,
        calibration_source="project",
    )
    assert target_row["low"] == pytest.approx(expected["low"])
    assert target_row["high"] == pytest.approx(expected["high"])
    assert target_row["within"] is True


def test_malformed_rows_are_skipped_without_crashing() -> None:
    rows: list[Any] = [
        None,
        "not-a-dict",
        {"project_id": 7, "predicted_conversion_rate": None},
        {"project_id": 7, "predicted_conversion_rate": "bad"},
        {
            "project_id": 7,
            "predicted_conversion_rate": True,
            "actual_conversion_rate": 0.05,
        },
        {
            "project_id": 7,
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": float("nan"),
        },
        _row(row_id=1, project_id=7, predicted=0.10, actual=0.09),
    ]
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    assert payload["total_project_outcomes"] == 1
    assert payload["evaluated_runs"] == 0
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA


def test_schema_round_trip() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.11, 0.09, 0.11])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)
    out = PredictionRangeCoverageOut(**payload)

    assert out.project_id == 7
    assert out.evaluated_runs == 3
    assert out.coverage_rate == pytest.approx(1.0)
    assert out.verdict == VERDICT_WELL_CALIBRATED
    assert len(out.rows) == 6
    assert len(out.key_signals) >= 3


def test_key_signals_include_verdict() -> None:
    rows = _target_rows([0.09, 0.11, 0.09, 0.50, 0.05, 0.55])
    payload = build_prediction_range_coverage(project_id=7, rows=rows)

    signals = {signal["label"]: signal for signal in payload["key_signals"]}
    assert signals["verdict"]["value"] == VERDICT_POORLY_CALIBRATED
    assert signals["coverage_rate"]["value"] == pytest.approx(1 / 3)
    assert signals["worst_miss_simulation"]["value"] is not None
