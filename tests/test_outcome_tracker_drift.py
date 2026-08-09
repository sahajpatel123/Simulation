"""Tests for the post-launch tracking-drift early-warning feature."""
from __future__ import annotations

import math
import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub

from app.schemas.outcome_tracker import OutcomeTrackerDriftOut
from app.simulation.outcome_tracker_drift import (
    DRIFT_INSUFFICIENT_DATA,
    DRIFT_NARROWING,
    DRIFT_STABLE,
    DRIFT_WIDENING,
    TRACKING_AHEAD,
    TRACKING_BEHIND,
    TRACKING_INSUFFICIENT_DATA,
    TRACKING_ON_TRACK,
    build_outcome_tracker_drift,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _row(rid: int, *, day: float, rate: float) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": 7,
        "simulation_id": 12,
        "recorded_at": (BASE + timedelta(days=day)).isoformat(),
        "actual_conversion_rate": rate,
        "actual_revenue": None,
        "predicted_conversion_rate": None,
        "predicted_revenue": None,
        "variance": None,
        "notes": None,
    }


def _call(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int = 7,
    predicted: float | None = None,
) -> dict[str, Any]:
    return build_outcome_tracker_drift(
        rows,
        project_id=project_id,
        predicted_conversion_rate=predicted,
    )


# ---------------------------------------------------------------------------
# Pure builder — insufficient data
# ---------------------------------------------------------------------------


def test_empty_rows_are_insufficient() -> None:
    out = _call(None, predicted=0.05)
    assert out["project_id"] == 7
    assert out["sample_count"] == 0
    assert out["span_days"] is None
    assert out["latest_actual"] is None
    assert out["predicted_conversion_rate"] == 0.05
    assert out["tracking_status"] == TRACKING_INSUFFICIENT_DATA
    assert out["drift_direction"] == DRIFT_INSUFFICIENT_DATA
    assert out["severity"] == "watch"
    assert out["checks"] == []
    assert "at least 3 conversion checkpoints" in out["narrative"]


def test_single_point_is_insufficient() -> None:
    out = _call([_row(1, day=0.0, rate=0.05)], predicted=0.05)
    assert out["sample_count"] == 0
    assert out["latest_actual"] == 0.05
    assert out["tracking_status"] == TRACKING_INSUFFICIENT_DATA


def test_two_points_cannot_form_a_step() -> None:
    """Two checkpoints satisfy the forecast minimum but leave no next point."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.08),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 0
    assert out["span_days"] == 30.0
    assert out["latest_actual"] == 0.08
    assert out["tracking_status"] == TRACKING_INSUFFICIENT_DATA
    assert "at least 3 conversion checkpoints" in out["narrative"]


def test_same_day_points_collapse_to_one() -> None:
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=0.0, rate=0.08),
            _row(3, day=30.0, rate=0.09),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 0
    assert out["latest_actual"] == 0.09
    assert out["tracking_status"] == TRACKING_INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Pure builder — tracking status, drift direction, severity
# ---------------------------------------------------------------------------


def test_linear_series_tracks_the_expected_path() -> None:
    """A series that follows a straight line must report ON_TRACK / STABLE."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.20),
            _row(2, day=30.0, rate=0.19),
            _row(3, day=60.0, rate=0.18),
            _row(4, day=90.0, rate=0.17),
            _row(5, day=120.0, rate=0.16),
            _row(6, day=150.0, rate=0.15),
            _row(7, day=180.0, rate=0.14),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 5
    assert out["tracking_status"] == TRACKING_ON_TRACK
    assert out["drift_direction"] == DRIFT_STABLE
    assert out["severity"] == "ok"
    assert out["mean_tracking_error_pp"] is not None
    assert abs(out["mean_tracking_error_pp"]) < 0.01
    assert out["mean_abs_tracking_error_pp"] < 0.01
    assert len(out["checks"]) == 5


def test_behind_and_widening_gap_is_critical() -> None:
    """A peak-and-fall series must flag a widening shortfall as critical."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.18),
            _row(2, day=30.0, rate=0.22),
            _row(3, day=60.0, rate=0.25),
            _row(4, day=90.0, rate=0.23),
            _row(5, day=120.0, rate=0.20),
            _row(6, day=150.0, rate=0.16),
            _row(7, day=180.0, rate=0.11),
        ],
        predicted=0.25,
    )
    assert out["sample_count"] == 5
    assert out["tracking_status"] == TRACKING_BEHIND
    assert out["drift_direction"] == DRIFT_WIDENING
    assert out["severity"] == "critical"
    assert out["mean_tracking_error_pp"] is not None
    assert out["mean_tracking_error_pp"] > 2.0
    assert out["gap_slope_pp_per_check"] is not None
    assert out["gap_slope_pp_per_check"] > 0.5
    assert out["latest_tracking_error_pp"] is not None
    assert out["latest_tracking_error_pp"] > 2.0
    assert "widening" in out["narrative"]
    assert "optimistic" in out["narrative"]


def test_behind_but_narrowing_gap_is_watch() -> None:
    """A shortfall that is closing must be watch, not critical."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.20),
            _row(3, day=60.0, rate=0.18),
            _row(4, day=90.0, rate=0.17),
            _row(5, day=120.0, rate=0.165),
            _row(6, day=150.0, rate=0.16),
        ],
        predicted=0.25,
    )
    assert out["sample_count"] == 4
    assert out["tracking_status"] == TRACKING_BEHIND
    assert out["drift_direction"] == DRIFT_NARROWING
    assert out["severity"] == "watch"
    assert out["gap_slope_pp_per_check"] is not None
    assert out["gap_slope_pp_per_check"] < -0.5
    assert "closing" in out["narrative"]


def test_ahead_and_widening_lead_is_watch() -> None:
    """Accelerating growth must flag an upside gap and pessimistic forecast."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.06),
            _row(3, day=60.0, rate=0.10),
            _row(4, day=90.0, rate=0.17),
            _row(5, day=120.0, rate=0.27),
            _row(6, day=150.0, rate=0.40),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 4
    assert out["tracking_status"] == TRACKING_AHEAD
    assert out["drift_direction"] == DRIFT_WIDENING
    assert out["severity"] == "watch"
    assert out["mean_tracking_error_pp"] is not None
    assert out["mean_tracking_error_pp"] < -2.0
    assert "under-predicting demand" in out["narrative"]


def test_fewer_than_three_steps_has_no_drift_direction() -> None:
    """Two tracked steps can judge status but not whether the gap is moving."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.15),
            _row(3, day=60.0, rate=0.30),
            _row(4, day=90.0, rate=0.25),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 2
    assert out["drift_direction"] == DRIFT_INSUFFICIENT_DATA
    assert out["gap_slope_pp_per_check"] is None
    assert "Log 1 more checkpoint" in out["narrative"]


def test_one_tracked_step_guidance_asks_for_two_more() -> None:
    """One tracked step needs two more checkpoints before drift direction."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.10),
            _row(3, day=60.0, rate=0.08),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 1
    assert out["tracking_status"] == TRACKING_BEHIND
    assert out["drift_direction"] == DRIFT_INSUFFICIENT_DATA
    assert "Log 2 more checkpoints" in out["narrative"]


# ---------------------------------------------------------------------------
# Pure builder — robustness
# ---------------------------------------------------------------------------


def test_malformed_rows_are_dropped() -> None:
    rows = [
        {"id": 1, "recorded_at": None, "actual_conversion_rate": 0.05},
        {"id": 2, "recorded_at": "not-a-timestamp", "actual_conversion_rate": 0.05},
        {"id": 3, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_conversion_rate": "bad"},
        {"id": 4, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_conversion_rate": float("nan")},
        {"id": 5, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_conversion_rate": True},
        _row(6, day=0.0, rate=0.05),
        _row(7, day=30.0, rate=0.10),
        _row(8, day=60.0, rate=0.10),
        _row(9, day=90.0, rate=0.09),
        _row(10, day=120.0, rate=0.08),
        _row(11, day=150.0, rate=0.07),
    ]
    clean = _call(
        [
            _row(6, day=0.0, rate=0.05),
            _row(7, day=30.0, rate=0.10),
            _row(8, day=60.0, rate=0.10),
            _row(9, day=90.0, rate=0.09),
            _row(10, day=120.0, rate=0.08),
            _row(11, day=150.0, rate=0.07),
        ],
        predicted=0.05,
    )
    out = _call(rows, predicted=0.05)
    assert out["sample_count"] == clean["sample_count"] == 4
    assert out["mean_tracking_error_pp"] == clean["mean_tracking_error_pp"]
    assert out["tracking_status"] == clean["tracking_status"]
    assert out["drift_direction"] == clean["drift_direction"]


def test_duplicate_timestamps_keep_last_row() -> None:
    rows = [
        _row(1, day=0.0, rate=0.05),
        _row(2, day=30.0, rate=0.10),
        _row(3, day=60.0, rate=0.09),
        _row(4, day=90.0, rate=0.08),
        _row(5, day=120.0, rate=0.07),
        _row(6, day=150.0, rate=0.06),
        _row(7, day=180.0, rate=0.05),
        _row(8, day=180.0, rate=0.08),  # same timestamp, later rate wins
    ]
    expected = [
        _row(1, day=0.0, rate=0.05),
        _row(2, day=30.0, rate=0.10),
        _row(3, day=60.0, rate=0.09),
        _row(4, day=90.0, rate=0.08),
        _row(5, day=120.0, rate=0.07),
        _row(6, day=150.0, rate=0.06),
        _row(7, day=180.0, rate=0.08),
    ]
    out = _call(rows, predicted=0.05)
    exp = _call(expected, predicted=0.05)
    assert out["sample_count"] == exp["sample_count"] == 5
    assert out["mean_tracking_error_pp"] == exp["mean_tracking_error_pp"]
    assert out["latest_tracking_error_pp"] == exp["latest_tracking_error_pp"]
    assert out["checks"][-1]["actual_conversion_rate"] == 0.08


def test_extreme_values_stay_finite_and_bounded() -> None:
    """Zero and 100% actuals must not produce NaN/Infinity aggregates."""
    out = _call(
        [
            _row(1, day=0.0, rate=0.05),
            _row(2, day=30.0, rate=0.05),
            _row(3, day=60.0, rate=0.0),
            _row(4, day=90.0, rate=0.0),
            _row(5, day=120.0, rate=1.0),
            _row(6, day=150.0, rate=1.0),
            _row(7, day=180.0, rate=1.0),
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 5
    for key in (
        "mean_tracking_error_pp",
        "mean_abs_tracking_error_pp",
        "latest_tracking_error_pp",
        "gap_slope_pp_per_check",
    ):
        value = out[key]
        if value is not None:
            assert math.isfinite(value)
    for check in out["checks"]:
        assert math.isfinite(check["expected_conversion_rate"])
        assert math.isfinite(check["actual_conversion_rate"])
        assert math.isfinite(check["deviation_pp"])
    assert 0.0 <= out["checks"][-1]["expected_conversion_rate"] <= 1.0


def test_checks_history_is_bounded() -> None:
    out = _call(
        [
            _row(i + 1, day=day, rate=0.20 - 0.001 * day)
            for i, day in enumerate(range(0, 720, 30))
        ],
        predicted=0.05,
    )
    assert out["sample_count"] == 22
    assert len(out["checks"]) == 12


def test_schema_accepts_builder_payload() -> None:
    out = OutcomeTrackerDriftOut(
        **_call(
            [
                _row(1, day=0.0, rate=0.20),
                _row(2, day=30.0, rate=0.19),
                _row(3, day=60.0, rate=0.18),
                _row(4, day=90.0, rate=0.17),
                _row(5, day=120.0, rate=0.16),
            ],
            predicted=0.05,
        )
    )
    assert out.project_id == 7
    assert out.sample_count == 3
    assert out.tracking_status == TRACKING_ON_TRACK
    assert out.checks[0].expected_conversion_rate > 0.0


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def all(self) -> list[Any]:
        return self._items


class _FakeSimulation:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.id = 12
        self.results_json = results if results is not None else {"mean_conversion_rate": 0.05}


class _FakeSession:
    def __init__(
        self,
        *,
        rows: list[Any] | None = None,
        sim: _FakeSimulation | None = None,
        project_items: list[Any] | None = None,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._sim = sim
        self._project_items = project_items if project_items is not None else [object()]

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery(self._project_items)
        if name == "Simulation":
            return _FakeQuery([self._sim] if self._sim is not None else [])
        if name == "OutcomeTracker":
            return _FakeQuery(self._rows)
        return _FakeQuery([])


def _make_tracker_row(
    rid: int,
    *,
    rate: float,
    day: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid,
        project_id=7,
        simulation_id=12,
        recorded_at=BASE + timedelta(days=day),
        actual_conversion_rate=rate,
        actual_revenue=None,
        predicted_conversion_rate=None,
        predicted_revenue=None,
        variance=None,
        notes=None,
    )


def _call_route(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_drift(
        project_id=7,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_route_returns_drift_with_sim_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(i, rate=0.20 - 0.001 * day, day=day)
            for i, day in enumerate(range(0, 181, 30))
        ],
        sim=_FakeSimulation(results={"mean_conversion_rate": 0.05}),
    )
    out = _call_route(session=session)
    assert out.project_id == 7
    assert out.sample_count == 5
    assert out.tracking_status == TRACKING_ON_TRACK
    assert out.severity == "ok"
    assert len(out.checks) == 5


def test_route_falls_back_to_row_prediction_when_no_simulation() -> None:
    rows = [
        _make_tracker_row(i, rate=0.18 - 0.002 * day, day=day)
        for i, day in enumerate(range(0, 181, 30))
    ]
    for row in rows:
        row.predicted_conversion_rate = 0.25
    session = _FakeSession(rows=rows, sim=None)
    out = _call_route(session=session)
    assert out.sample_count == 5
    assert out.tracking_status in (TRACKING_ON_TRACK, TRACKING_BEHIND, TRACKING_AHEAD)


def test_route_uses_newest_row_prediction_when_no_simulation() -> None:
    """Legacy fallback must prefer the newest checkpoint's prediction."""
    rows = [
        _make_tracker_row(i, rate=0.20 - 0.001 * day, day=day)
        for i, day in enumerate(range(0, 181, 30))
    ]
    for idx, row in enumerate(rows):
        row.predicted_conversion_rate = 0.05 if idx < len(rows) - 1 else 0.35
    session = _FakeSession(rows=rows, sim=None)
    out = _call_route(session=session)
    assert out.predicted_conversion_rate == 0.35


def test_route_empty_tracker_is_insufficient() -> None:
    out = _call_route(session=_FakeSession(rows=[]))
    assert out.sample_count == 0
    assert out.tracking_status == TRACKING_INSUFFICIENT_DATA


def test_route_requires_project_ownership() -> None:
    session = _FakeSession(project_items=[])
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, user_id=42)
    assert exc.value.status_code == 404
