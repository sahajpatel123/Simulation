"""Tests for the post-launch goal-pacing verdict feature."""
from __future__ import annotations

from datetime import date
from typing import Any


def _row(
    rid: int,
    *,
    recorded_at: str,
    actual: float | None = None,
    revenue: float | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": 7,
        "simulation_id": 12,
        "recorded_at": recorded_at,
        "actual_conversion_rate": actual,
        "actual_revenue": revenue,
        "predicted_conversion_rate": None,
        "predicted_revenue": None,
        "variance": None,
        "notes": None,
    }


def _call_pacing(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int = 7,
    target_conversion_rate: float | None = None,
    target_revenue: float | None = None,
    deadline: date | None = None,
) -> dict[str, Any]:
    from app.simulation.outcome_tracker_goal_pacing import (
        build_outcome_tracker_goal_pacing,
    )

    return build_outcome_tracker_goal_pacing(
        rows,
        project_id=project_id,
        target_conversion_rate=target_conversion_rate,
        target_revenue=target_revenue,
        deadline=deadline,
    )


def _weekly_conversion_rows() -> list[dict[str, Any]]:
    return [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.03),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=0.05),
    ]


def test_pacing_without_targets_is_insufficient() -> None:
    out = _call_pacing(_weekly_conversion_rows())
    assert out["project_id"] == 7
    assert out["metrics"] == []
    assert out["overall_status"] == "INSUFFICIENT_DATA"
    assert "target_conversion_rate" in out["narrative"]


def test_pacing_empty_rows_is_insufficient() -> None:
    out = _call_pacing(None, target_conversion_rate=0.05)
    assert out["overall_status"] == "INSUFFICIENT_DATA"
    metric = out["metrics"][0]
    assert metric["metric"] == "conversion"
    assert metric["sample_count"] == 0
    assert metric["status"] == "INSUFFICIENT_DATA"
    assert metric["confidence"] == "INSUFFICIENT_DATA"
    assert metric["latest_actual"] is None
    assert "Log at least 2" in metric["narrative"]


def test_pacing_single_point_is_insufficient() -> None:
    rows = [_row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03)]
    out = _call_pacing(rows, target_conversion_rate=0.05)
    metric = out["metrics"][0]
    assert metric["sample_count"] == 1
    assert metric["latest_actual"] == 0.03
    assert metric["status"] == "INSUFFICIENT_DATA"


def test_pacing_skips_malformed_rows() -> None:
    rows = [
        {"id": 1, "recorded_at": None, "actual_conversion_rate": 0.03},
        {
            "id": 2,
            "recorded_at": "not-a-timestamp",
            "actual_conversion_rate": 0.04,
        },
        {
            "id": 3,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": "bad",
        },
        {
            "id": 4,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": float("nan"),
        },
        {
            "id": 5,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": True,
        },
        _row(6, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(7, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_pacing(rows, target_conversion_rate=0.05)
    metric = out["metrics"][0]
    assert metric["sample_count"] == 2
    assert metric["span_days"] == 14.0
    assert metric["latest_actual"] == 0.04


def test_pacing_sorts_and_deduplicates_rows() -> None:
    rows = [
        _row(1, recorded_at="2026-08-20T00:00:00+00:00", actual=0.05),
        _row(2, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02),
        {
            "id": 3,
            "recorded_at": "2026-08-08T00:00:00+00:00",
            "actual_conversion_rate": 0.025,
        },
        {
            "id": 4,
            "recorded_at": "2026-08-08T00:00:00+00:00",
            "actual_conversion_rate": 0.03,
        },
    ]
    out = _call_pacing(rows, target_conversion_rate=0.05)
    metric = out["metrics"][0]
    assert metric["sample_count"] == 3
    assert metric["latest_actual"] == 0.05
    assert metric["status"] == "ALREADY_ACHIEVED"


def test_pacing_already_achieved() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.04,
        deadline=date(2026, 8, 29),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "ALREADY_ACHIEVED"
    assert metric["latest_actual"] == 0.05
    assert "already meets" in metric["narrative"]
    assert out["overall_status"] == "ALREADY_ACHIEVED"


def test_pacing_on_track_conversion() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.06,
        deadline=date(2026, 8, 29),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "ON_TRACK"
    assert metric["trend_label"] == "CONVERGING"
    assert metric["confidence"] == "HIGH"
    assert metric["deadline_days"] == 7.0
    assert metric["projected_value_at_deadline"] >= 0.06
    assert metric["days_to_target"] == 7.0
    assert metric["required_slope_per_day"] is not None
    assert metric["gap_at_deadline"] is not None
    assert metric["gap_at_deadline"] <= 0.0
    labels = {signal["label"] for signal in metric["signals"]}
    assert {
        "latest_actual",
        "trend",
        "deadline_projection",
        "days_to_target",
        "required_slope",
        "confidence",
    } <= labels
    assert "on track" in metric["narrative"]


def test_pacing_behind_conversion_shows_required_pace() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.08,
        deadline=date(2026, 8, 25),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "BEHIND"
    assert metric["deadline_days"] == 3.0
    assert metric["projected_value_at_deadline"] == 0.054287
    assert metric["gap_at_deadline"] == 0.025713
    assert metric["required_slope_per_day"] == 0.01
    assert metric["slope_gap_per_day"] == 0.008571
    assert metric["days_to_target"] == 21.0
    assert "behind" in metric["narrative"]
    assert "You need 1.000pp/day" in metric["narrative"]
    required_signal = next(
        signal
        for signal in metric["signals"]
        if signal["label"] == "required_slope"
    )
    assert required_signal["severity"] == "critical"


def test_pacing_flat_series_is_stalled() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.03),
    ]
    out = _call_pacing(
        rows,
        target_conversion_rate=0.05,
        deadline=date(2026, 8, 15),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "STALLED"
    assert metric["trend_label"] == "FLAT"
    assert metric["projected_value_at_deadline"] == 0.03
    assert metric["gap_at_deadline"] == 0.02
    assert metric["days_to_target"] is None
    assert "stalled" in metric["narrative"]
    assert out["overall_status"] == "STALLED"


def test_pacing_declining_series_is_stalled() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.05),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.045),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_pacing(
        rows,
        target_conversion_rate=0.06,
        deadline=date(2026, 8, 22),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "STALLED"
    assert metric["trend_label"] == "DECLINING"
    assert "falling" in metric["narrative"]


def test_pacing_expired_deadline() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.08,
        deadline=date(2026, 8, 20),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "EXPIRED"
    assert metric["deadline_days"] == -2.0
    assert metric["projected_value_at_deadline"] == 0.05
    assert metric["gap_at_deadline"] == 0.03
    assert "has passed" in metric["narrative"]
    assert out["overall_status"] == "EXPIRED"


def test_pacing_deadline_today_is_expired() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.08,
        deadline=date(2026, 8, 22),
    )
    metric = out["metrics"][0]
    assert metric["status"] == "EXPIRED"
    assert metric["deadline_days"] == 0.0
    assert metric["projected_value_at_deadline"] == 0.05


def test_pacing_without_deadline_reports_trend_days() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.06,
    )
    metric = out["metrics"][0]
    assert metric["status"] == "NO_DEADLINE"
    assert metric["deadline_days"] is None
    assert metric["projected_value_at_deadline"] is None
    assert metric["gap_at_deadline"] is None
    assert metric["days_to_target"] == 7.0
    assert "Add a deadline" in metric["narrative"]
    assert out["deadline"] is None
    assert out["deadline_days"] is None
    assert out["overall_status"] == "NO_DEADLINE"


def test_pacing_revenue_metric() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", revenue=1000.0),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", revenue=2000.0),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", revenue=3000.0),
    ]
    out = _call_pacing(
        rows,
        target_revenue=6000.0,
        deadline=date(2026, 8, 22),
    )
    metric = out["metrics"][0]
    assert metric["metric"] == "revenue"
    assert metric["status"] == "BEHIND"
    assert metric["trend_label"] == "CONVERGING"
    assert metric["slope_per_day"] == 142.857143
    assert metric["projected_value_at_deadline"] == 4000.0
    assert metric["gap_at_deadline"] == 2000.0
    assert metric["required_slope_per_day"] == 428.571429
    assert metric["slope_gap_per_day"] == 285.714286
    assert metric["days_to_target"] == 21.0
    assert "₹" in metric["narrative"]


def test_pacing_both_metrics_overall_is_worst() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02, revenue=1000.0),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.03, revenue=2000.0),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04, revenue=3000.0),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=0.05, revenue=4000.0),
    ]
    out = _call_pacing(
        rows,
        target_conversion_rate=0.04,
        target_revenue=6000.0,
        deadline=date(2026, 8, 29),
    )
    assert len(out["metrics"]) == 2
    statuses = {metric["status"] for metric in out["metrics"]}
    assert statuses == {"ALREADY_ACHIEVED", "BEHIND"}
    assert out["overall_status"] == "BEHIND"
    assert out["deadline_days"] == 7.0
    assert "Accelerate" in out["narrative"]
    assert len(out["key_signals"]) >= len(out["metrics"])


def test_pacing_zero_target_is_tolerated_as_insufficient() -> None:
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.0,
    )
    metric = out["metrics"][0]
    assert metric["status"] == "INSUFFICIENT_DATA"
    assert metric["target_value"] == 0.0


def test_pacing_schema_validates_payload() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerGoalPacingOut

    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=0.06,
        target_revenue=6000.0,
        deadline=date(2026, 8, 29),
    )
    parsed = OutcomeTrackerGoalPacingOut(**out)
    assert parsed.project_id == 7
    assert parsed.deadline == date(2026, 8, 29)
    assert parsed.overall_status in {
        metric.status for metric in parsed.metrics
    }
