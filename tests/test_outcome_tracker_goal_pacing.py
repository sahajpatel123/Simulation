"""Tests for the post-launch goal-pacing verdict feature."""
from __future__ import annotations

import math
import sys
import types
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub


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


def test_pacing_out_of_range_conversion_target_is_clamped_and_echoed() -> None:
    """A >100% conversion goal is clamped to 100% everywhere in the payload."""
    out = _call_pacing(
        _weekly_conversion_rows(),
        target_conversion_rate=1.5,
        deadline=date(2026, 8, 29),
    )
    metric = out["metrics"][0]
    assert metric["target_value"] == 1.0
    assert metric["status"] == "BEHIND"
    assert "100.00% goal" in metric["narrative"]


def test_pacing_non_finite_or_invalid_targets_degrade_to_no_goal() -> None:
    """NaN/Infinity/boolean/non-positive goals never leak into the payload."""
    rows = _weekly_conversion_rows()
    for bad_target in (float("inf"), float("nan"), -0.5, True):
        out = _call_pacing(rows, target_conversion_rate=bad_target)
        metric = out["metrics"][0]
        assert math.isfinite(metric["target_value"])
        assert metric["target_value"] == 0.0
        assert metric["status"] == "INSUFFICIENT_DATA"
        assert "Set a valid conversion goal" in metric["narrative"]
    for bad_target in (float("inf"), float("nan"), -100.0, True):
        out = _call_pacing(rows, target_revenue=bad_target)
        metric = out["metrics"][0]
        assert math.isfinite(metric["target_value"])
        assert metric["target_value"] == 0.0
        assert metric["status"] == "INSUFFICIENT_DATA"
        assert "Set a valid revenue goal" in metric["narrative"]


def test_pacing_schema_rejects_non_finite_target_value() -> None:
    from pydantic import ValidationError

    from app.schemas.outcome_tracker import OutcomeTrackerGoalMetric

    for bad_value in (float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            OutcomeTrackerGoalMetric(
                metric="conversion",
                target_value=bad_value,
            )


# ---------------------------------------------------------------------------
# Route smoke tests (fake session, no DB)
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, user_id: int = 42) -> None:
        self.id = 7
        self.user_id = user_id


class _FakeQuery:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self.items[0] if self.items else None

    def all(self) -> list[Any]:
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _FakeProject | None = None,
        project_items: list[Any] | None = None,
        rows: list[Any] | None = None,
    ) -> None:
        self.project = project if project is not None else _FakeProject()
        self.project_items = project_items
        self.rows = rows if rows is not None else []

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project_items is not None:
                return _FakeQuery(self.project_items)
            return _FakeQuery([self.project])
        if name == "OutcomeTracker":
            return _FakeQuery(self.rows)
        return _FakeQuery([])


def _route_row(
    rid: int,
    *,
    recorded_at: str,
    actual: float | None = None,
    revenue: float | None = None,
) -> Any:
    return types.SimpleNamespace(
        id=rid,
        project_id=7,
        simulation_id=12,
        recorded_at=recorded_at,
        actual_conversion_rate=actual,
        actual_revenue=revenue,
        predicted_conversion_rate=None,
        predicted_revenue=None,
        variance=None,
        notes=None,
    )


def _call_route(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
    target_conversion_rate: float | None = None,
    target_revenue: float | None = None,
    deadline: date | None = None,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_goal_pacing(
        project_id=7,
        target_conversion_rate=target_conversion_rate,
        target_revenue=target_revenue,
        deadline=deadline,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_goal_pacing_route_returns_payload_for_both_metrics() -> None:
    session = _FakeSession(
        rows=[
            _route_row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02, revenue=1000.0),
            _route_row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.03, revenue=2000.0),
            _route_row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04, revenue=3000.0),
            _route_row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=0.05, revenue=4000.0),
        ]
    )
    out = _call_route(
        session=session,
        target_conversion_rate=0.06,
        target_revenue=6000.0,
        deadline=date(2026, 8, 29),
    )
    assert out.project_id == 7
    assert out.deadline == date(2026, 8, 29)
    assert len(out.metrics) == 2
    statuses = {metric.status for metric in out.metrics}
    assert statuses == {"ON_TRACK", "BEHIND"}
    assert out.overall_status == "BEHIND"


def test_goal_pacing_route_rejects_missing_targets() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route()
    assert exc.value.status_code == 422
    assert "at least one" in exc.value.detail


def test_goal_pacing_route_rejects_non_positive_targets() -> None:
    for target_kwargs in (
        {"target_conversion_rate": 0.0},
        {"target_conversion_rate": -0.01},
        {"target_revenue": 0.0},
        {"target_revenue": -5.0},
    ):
        with pytest.raises(HTTPException) as exc:
            _call_route(**target_kwargs)
        assert exc.value.status_code == 422
        assert "must be greater than 0" in exc.value.detail


def test_goal_pacing_route_rejects_foreign_project() -> None:
    # No owned project row matches, so ownership lookup raises 404.
    session = _FakeSession(project_items=[])
    with pytest.raises(HTTPException) as exc:
        _call_route(
            session=session,
            target_conversion_rate=0.05,
        )
    assert exc.value.status_code == 404
