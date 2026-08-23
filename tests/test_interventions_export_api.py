"""Route-level tests for the /projects/{id}/interventions/export endpoint."""
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


class _Project:
    def __init__(self) -> None:
        self.id = 10
        self.interventions_json = {
            "interventions": [
                {
                    "id": "i1",
                    "title": "Run pricing test",
                    "description": "Test different price points",
                    "expected_impact": "High",
                    "difficulty": "MEDIUM",
                    "estimated_cost": "$500",
                    "linked_assumption": "willing to pay",
                    "linked_failure_mode": "price too low",
                    "priority_score": 0.9,
                    "time_to_implement": "2 weeks",
                    "success_metric": "conversion",
                }
            ],
            "quick_wins": [],
        }


class _EmptyProject(_Project):
    def __init__(self) -> None:
        # Independent initializer: this fake intentionally differs
        # from _Project only in its payload attribute.
        self.id = 10
        self.interventions_json = None


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, project: object | None = None) -> None:
        self.project = project if project is not None else _Project()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_interventions(
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


def test_export_interventions_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="interventions-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "list_type,id,title,description" in body
    assert "interventions,i1,Run pricing test" in body
    assert "user_id,42" in body


def test_export_interventions_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"title": "Run pricing test"' in body


def test_export_interventions_empty_returns_header_only() -> None:
    session = _FakeSession(_EmptyProject())
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "list_type,id,title,description" in body
    assert "interventions,i1,Run pricing test" not in body


def test_export_interventions_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            return _FakeQuery([])

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
