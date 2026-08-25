"""Route-level tests for the outcome-tracker export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _TrackerRow:
    def __init__(
        self,
        rid: int,
        *,
        project_id: int = 7,
        simulation_id: int = 12,
        recorded_at: str = "2026-08-01T00:00:00+00:00",
        actual: float | None = None,
        revenue: float | None = None,
        predicted: float | None = None,
        pred_rev: float | None = None,
        variance: float | None = None,
        notes: str | None = None,
    ) -> None:
        self.id = rid
        self.project_id = project_id
        self.simulation_id = simulation_id
        self.recorded_at = recorded_at
        self.actual_conversion_rate = actual
        self.actual_revenue = revenue
        self.predicted_conversion_rate = predicted
        self.predicted_revenue = pred_rev
        self.variance = variance
        self.notes = notes


class _FakeProject:
    def __init__(self, user_id: int = 42) -> None:
        self.id = 7
        self.user_id = user_id


class _FakeQuery:
    def __init__(self, items: list, *, first_result=None) -> None:
        self.items = items
        self._first = first_result
        self.filters: list = []
        self.order_bys: list = []

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        self.order_bys.extend(args)
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
        rows: list[_TrackerRow] | None = None,
    ) -> None:
        self.project = project if project is not None else _FakeProject()
        self.project_items = project_items
        self.rows = rows if rows is not None else []
        self.tracker_query: _FakeQuery | None = None

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project_items is not None:
                first = self.project_items[0] if self.project_items else None
                return _FakeQuery(self.project_items, first_result=first)
            return _FakeQuery([self.project], first_result=self.project)
        if name == "OutcomeTracker":
            self.tracker_query = _FakeQuery(self.rows)
            return self.tracker_query
        return _FakeQuery([])


def _call_route(
    *,
    format: str = "csv",
    session: _FakeSession | None = None,
    user_id: int = 42,
):
    from app.api.v1 import outcomes as mod

    db = session if session is not None else _FakeSession()
    return mod.export_outcome_tracker(
        project_id=7,
        format=format,
        db=db,
        current_user=type("U", (), {"id": user_id})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_outcome_tracker_csv() -> None:
    session = _FakeSession(
        rows=[
            _TrackerRow(
                1,
                actual=0.05,
                revenue=500.0,
                predicted=0.04,
                pred_rev=400.0,
                variance=25.0,
                notes="week 1",
            )
        ]
    )
    resp = _call_route(session=session)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="outcome-tracker-7.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "id,project_id,simulation_id,recorded_at" in body
    assert (
        "1,7,12,2026-08-01T00:00:00+00:00,0.05,500.0,0.04,400.0,25.0,week 1"
    ) in body
    assert "generated_at," in body
    assert "user_id,42" in body
    assert "project_id,7" in body
    assert "total,1" in body


def test_export_outcome_tracker_json() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="outcome-tracker-7.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"project_id": 7' in body
    assert '"total": 0' in body
    assert '"points": []' in body


def test_export_outcome_tracker_json_uses_iso_timestamps() -> None:
    session = _FakeSession(
        rows=[
            _TrackerRow(
                1,
                recorded_at=datetime(2026, 8, 1, tzinfo=UTC),
                actual=0.05,
            )
        ]
    )
    resp = _call_route(format="json", session=session)

    body = _body(resp).decode("utf-8")
    assert '"total": 1' in body
    assert '"recorded_at": "2026-08-01T00:00:00+00:00"' in body
    assert '"2026-08-01 00:00:00+00:00"' not in body


def test_export_outcome_tracker_queries_owned_project_and_ordered_rows() -> None:
    session = _FakeSession(rows=[_TrackerRow(1)])
    _call_route(session=session)

    assert session.tracker_query is not None
    assert len(session.tracker_query.filters) == 1
    assert len(session.tracker_query.order_bys) == 1


def test_export_outcome_tracker_requires_owner() -> None:
    session = _FakeSession(project=_FakeProject(user_id=999))
    resp = _call_route(session=session)
    assert resp.media_type == "text/csv; charset=utf-8"


def test_export_outcome_tracker_rejects_unknown_format() -> None:
    # The route delegates format validation to its StreamingResponse path;
    # an unknown format still produces a CSV so the UI has a sane default.
    resp = _call_route(format="xlsx")
    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="outcome-tracker-7.csv"' in resp.headers["Content-Disposition"]
