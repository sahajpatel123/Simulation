"""Tests for the per-project conversion-tracking timeline feature."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException


if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def _row(
    rid: int,
    *,
    project_id: int = 7,
    recorded_at: str | None = "2026-08-01T00:00:00+00:00",
    actual: float | None = None,
    revenue: float | None = None,
    predicted: float | None = None,
    pred_rev: float | None = None,
    variance: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": project_id,
        "simulation_id": 12,
        "recorded_at": recorded_at,
        "actual_conversion_rate": actual,
        "actual_revenue": revenue,
        "predicted_conversion_rate": predicted,
        "predicted_revenue": pred_rev,
        "variance": variance,
        "notes": notes,
    }


def test_helper_empty_state() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    out = build_outcome_tracker_timeline(None, project_id=1)
    assert out["project_id"] == 1
    assert out["total_points"] == 0
    assert out["points"] == []
    assert out["latest_predicted"] is None
    assert out["latest_actual"] is None
    assert out["latest_variance_pct"] is None
    assert out["mean_abs_variance_pct"] is None
    assert out["bias_direction"] == "INSUFFICIENT_DATA"


def test_helper_sorts_ascending_and_picks_latest() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    rows = [
        _row(2, recorded_at="2026-08-10T00:00:00+00:00", actual=0.08),
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.05),
        _row(3, recorded_at="2026-08-20T00:00:00+00:00", actual=0.10),
    ]
    out = build_outcome_tracker_timeline(rows, project_id=7)
    ids = [p["id"] for p in out["points"]]
    assert ids == [1, 2, 3]
    assert out["latest_actual"] == 0.10


def test_helper_latest_variance_uses_stored_variance() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    rows = [
        _row(1, variance=-10.0, actual=0.045, predicted=0.05),
        _row(2, variance=10.0, actual=0.055, predicted=0.05),
    ]
    out = build_outcome_tracker_timeline(rows, project_id=7)
    assert out["latest_variance_pct"] == 10.0
    assert out["mean_abs_variance_pct"] == 10.0
    assert out["bias_direction"] == "BALANCED"


def test_helper_over_predicting_direction() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    rows = [
        _row(1, variance=-10.0),
        _row(2, variance=-12.0),
        _row(3, variance=-9.0),
    ]
    out = build_outcome_tracker_timeline(rows, project_id=7)
    assert out["bias_direction"] == "OVER_PREDICTING"


def test_helper_under_predicting_direction() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    rows = [
        _row(1, variance=12.0),
        _row(2, variance=9.0),
        _row(3, variance=15.0),
    ]
    out = build_outcome_tracker_timeline(rows, project_id=7)
    assert out["bias_direction"] == "UNDER_PREDICTING"


def test_helper_ignores_rows_without_variance_for_bias() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    rows = [
        _row(1, actual=0.05, predicted=None, variance=None),
        _row(2, actual=0.04, predicted=0.05, variance=-20.0),
    ]
    out = build_outcome_tracker_timeline(rows, project_id=7)
    assert out["total_points"] == 2
    assert out["mean_abs_variance_pct"] == 20.0
    assert out["bias_direction"] == "OVER_PREDICTING"


def test_helper_converts_datetime_to_iso() -> None:
    from app.simulation.outcome_tracker_read import (
        build_outcome_tracker_timeline,
    )

    dt = datetime(2026, 8, 1, tzinfo=timezone.utc)
    row = _row(1, recorded_at=dt)
    out = build_outcome_tracker_timeline([row], project_id=7)
    assert out["points"][0]["recorded_at"] == "2026-08-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_schema_requires_at_least_one_metric() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerCreate

    with pytest.raises(ValueError):
        OutcomeTrackerCreate()

    ok = OutcomeTrackerCreate(actual_conversion_rate=0.05)
    assert ok.actual_conversion_rate == 0.05
    assert ok.actual_revenue is None

    ok2 = OutcomeTrackerCreate(actual_revenue=500.0)
    assert ok2.actual_conversion_rate is None
    assert ok2.actual_revenue == 500.0


def test_schema_rejects_extra_keys() -> None:
    from pydantic import ValidationError
    from app.schemas.outcome_tracker import OutcomeTrackerCreate

    with pytest.raises(ValidationError):
        OutcomeTrackerCreate(actual_conversion_rate=0.05, spam=True)


# ---------------------------------------------------------------------------
# Route smoke tests (fake session, no DB)
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, user_id: int = 42) -> None:
        self.id = 7
        self.user_id = user_id


class _FakeSimulation:
    def __init__(self, sim_id: int = 12, results: dict | None = None) -> None:
        self.id = sim_id
        self.project_id = 7
        self.status = "COMPLETED"
        self.results_json = results if results is not None else {
            "mean_conversion_rate": 0.05,
            "mean_revenue": 1000.0,
        }


class _FakeQuery:
    def __init__(self, items: list | None = None, *, first_result: Any = None) -> None:
        self.items = items if items is not None else []
        self._first = first_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self._first is not None:
            return self._first
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _FakeProject | None = None,
        project_items: list | None = None,
        sim: _FakeSimulation | None = None,
        sim_items: list | None = None,
        rows: list | None = None,
    ) -> None:
        self.project = project if project is not None else _FakeProject()
        self.project_items = project_items
        self.sim = sim if sim is not None else _FakeSimulation()
        self.sim_items = sim_items
        self.rows = rows if rows is not None else []
        self.added: list[Any] = []
        self.committed = 0
        self.refreshed: list[Any] = []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project_items is not None:
                return _FakeQuery(self.project_items)
            return _FakeQuery([self.project])
        if name == "Simulation":
            if self.sim_items is not None:
                return _FakeQuery(self.sim_items)
            return _FakeQuery([self.sim])
        if name == "OutcomeTracker":
            return _FakeQuery(self.rows)
        return _FakeQuery([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1
        self.refreshed.append(obj)


def _call_post(
    *,
    session: _FakeSession | None = None,
    payload: dict | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod
    from app.schemas.outcome_tracker import OutcomeTrackerCreate

    body = OutcomeTrackerCreate(
        **(payload if payload is not None else {"actual_conversion_rate": 0.06})
    )
    return mod.log_outcome_tracker_point(
        project_id=7,
        payload=body,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def _call_get(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_timeline(
        project_id=7,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_post_logs_tracker_point_with_predicted_values() -> None:
    session = _FakeSession()
    out = _call_post(session=session)

    assert session.committed == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.project_id == 7
    assert row.simulation_id == 12
    assert row.actual_conversion_rate == 0.06
    assert row.predicted_conversion_rate == 0.05
    assert row.variance == 20.0

    # Route returns the hydrated ORM row (no extra fields).
    assert out.project_id == 7
    assert out.actual_conversion_rate == 0.06
    assert out.predicted_conversion_rate == 0.05


def test_post_rejects_simulation_from_another_project() -> None:
    session = _FakeSession(sim_items=[])

    with pytest.raises(HTTPException) as exc:
        _call_post(
            session=session,
            payload={"simulation_id": 999, "actual_revenue": 100.0},
        )
    assert exc.value.status_code == 404


def test_get_returns_empty_timeline() -> None:
    out = _call_get()
    assert out.project_id == 7
    assert out.total_points == 0
    assert out.points == []


def test_get_returns_points_and_summary() -> None:
    from app.models.outcome_tracker import OutcomeTracker

    def make_row(rid: int, actual: float, variance: float) -> OutcomeTracker:
        r = OutcomeTracker(
            id=rid,
            project_id=7,
            simulation_id=12,
            actual_conversion_rate=actual,
            actual_revenue=100.0,
            predicted_conversion_rate=0.05,
            predicted_revenue=1000.0,
            variance=variance,
            notes=None,
            recorded_at=datetime(2026, 8, rid, tzinfo=timezone.utc),
        )
        return r

    session = _FakeSession(
        rows=[
            make_row(1, 0.04, -20.0),
            make_row(2, 0.06, 20.0),
        ]
    )
    out = _call_get(session=session)
    assert out.total_points == 2
    assert len(out.points) == 2
    assert out.mean_abs_variance_pct == 20.0
    assert out.bias_direction == "BALANCED"


def test_get_requires_project_ownership() -> None:
    session = _FakeSession(project_items=[])
    with pytest.raises(HTTPException) as exc:
        _call_get(session=session, user_id=42)
    assert exc.value.status_code == 404
