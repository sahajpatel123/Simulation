"""Route-level tests for the /projects/{id}/activity-feed/export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Row:
    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Project:
    def __init__(self) -> None:
        self.id = 10
        self.user_id = 42


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *_):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    def __init__(self, project: object | None = None) -> None:
        self.project = project if project is not None else _Project()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if not name and hasattr(model, "class_"):
            name = model.class_.__name__
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery(
                [
                    _Row(
                        id=1,
                        status="COMPLETED",
                        created_at="2026-01-01T00:00:00Z",
                        updated_at="2026-01-02T00:00:00Z",
                        results_json={"mean_conversion_rate": 0.042},
                    )
                ]
            )
        if name == "Decision":
            return _FakeQuery(
                [
                    _Row(
                        id=2,
                        status="COMPLETED",
                        title="Pivot to B2B?",
                        created_at="2026-01-01T00:00:00Z",
                        updated_at="2026-01-03T00:00:00Z",
                        results_json={
                            "recommended_scenario": "B2B Enterprise",
                            "winner_margin": 0.07,
                        },
                    )
                ]
            )
        if name == "Outcome":
            return _FakeQuery(
                [
                    _Row(
                        id=3,
                        created_at="2026-01-04T00:00:00Z",
                        actual_conversion_rate=0.052,
                    )
                ]
            )
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_activity_feed(
        project_id=project_id,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_activity_feed_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="activity-feed-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "type,occurred_at,ref_id,title,summary,severity" in body
    assert "user_id,42" in body
    assert "sim_completed" in body
    assert "outcome_submitted" in body
    assert "decision_completed" in body


def test_export_activity_feed_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"event_count"' in body
    assert '"sim_completed"' in body
    assert '"project_id": 10' in body


def test_export_activity_feed_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            if getattr(model, "__name__", "") == "Project":
                return _FakeQuery([])
            return super().query(model, *args, **kwargs)

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404


def test_export_activity_feed_route_registered() -> None:
    from app.api.v1 import projects as proj_mod

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/activity-feed/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/projects/{project_id}/activity-feed/export"]
