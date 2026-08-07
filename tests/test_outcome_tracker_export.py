"""Tests for the pure outcome-tracker CSV export helper."""
from __future__ import annotations

from datetime import datetime, timezone

from app.simulation.outcome_tracker_export import outcome_tracker_to_csv


def _row(
    rid: int,
    *,
    project_id: int = 7,
    simulation_id: int = 12,
    recorded_at: str | None = "2026-08-01T00:00:00+00:00",
    actual: float | None = None,
    revenue: float | None = None,
    predicted: float | None = None,
    pred_rev: float | None = None,
    variance: float | None = None,
    notes: str | None = None,
) -> dict:
    return {
        "id": rid,
        "project_id": project_id,
        "simulation_id": simulation_id,
        "recorded_at": recorded_at,
        "actual_conversion_rate": actual,
        "actual_revenue": revenue,
        "predicted_conversion_rate": predicted,
        "predicted_revenue": pred_rev,
        "variance": variance,
        "notes": notes,
    }


def test_csv_contains_header_rows_and_metadata() -> None:
    csv_text = outcome_tracker_to_csv(
        [_row(1, actual=0.05, revenue=500.0, predicted=0.04, pred_rev=400.0)],
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "project_id": 7,
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "project_id,7" in csv_text
    assert "format_version,1" in csv_text
    assert (
        "id,project_id,simulation_id,recorded_at,actual_conversion_rate,"
        "actual_revenue,predicted_conversion_rate,predicted_revenue,"
        "variance,notes"
    ) in csv_text
    assert (
        "1,7,12,2026-08-01T00:00:00+00:00,0.05,500.0,0.04,400.0,25.0,"
    ) in csv_text


def test_csv_empty_rows_only_has_header() -> None:
    csv_text = outcome_tracker_to_csv([])

    assert "id,project_id,simulation_id,recorded_at" in csv_text
    assert "1,7,12" not in csv_text


def test_csv_backfills_variance_when_stored_column_null() -> None:
    csv_text = outcome_tracker_to_csv(
        [
            _row(1, actual=0.06, predicted=0.05, variance=None),
            _row(2, actual=0.04, predicted=0.05, variance=None),
        ]
    )

    assert "1,7,12,2026-08-01T00:00:00+00:00,0.06,,0.05,,20.0," in csv_text
    assert "2,7,12,2026-08-01T00:00:00+00:00,0.04,,0.05,,-20.0," in csv_text


def test_csv_preserves_stored_variance_over_backfill() -> None:
    csv_text = outcome_tracker_to_csv(
        [
            _row(1, actual=0.99, predicted=0.01, variance=7.5),
        ]
    )

    assert ",0.99,,0.01,,7.5," in csv_text


def test_csv_sorts_ascending_and_puts_null_timestamps_last() -> None:
    rows = [
        _row(2, recorded_at="2026-08-10T00:00:00+00:00", actual=0.08),
        _row(3, recorded_at=None, actual=0.10),
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.05),
    ]
    csv_text = outcome_tracker_to_csv(rows)

    index1 = csv_text.find("1,7,12,2026-08-01")
    index2 = csv_text.find("2,7,12,2026-08-10")
    index3 = csv_text.find("3,7,12,")
    assert index1 != -1
    assert index2 != -1
    assert index3 != -1
    assert index1 < index2 < index3


def test_csv_handles_datetime_and_malformed_timestamps() -> None:
    csv_text = outcome_tracker_to_csv(
        [
            _row(
                1,
                recorded_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                actual=0.05,
            ),
            _row(2, recorded_at="not-a-timestamp", actual=0.06),
        ]
    )

    assert "1,7,12,2026-08-01T00:00:00+00:00,0.05" in csv_text
    assert "2,7,12,not-a-timestamp,0.06" in csv_text
    assert csv_text.find("1,7,12") < csv_text.find("2,7,12")


def test_csv_missing_fields_renders_empty() -> None:
    csv_text = outcome_tracker_to_csv(
        [
            {
                "id": 4,
                "project_id": 7,
                "simulation_id": None,
                "recorded_at": None,
                "actual_conversion_rate": 0.03,
                "actual_revenue": None,
                "predicted_conversion_rate": None,
                "predicted_revenue": None,
                "variance": None,
                "notes": None,
            }
        ]
    )

    assert "4,7,,,0.03,,,,,\n" in csv_text
