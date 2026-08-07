"""Route-level tests for the /projects/{id}/decisions/export endpoint."""
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


class _Decision:
    def __init__(self, decision_id: int = 1) -> None:
        self.id = decision_id
        self.project_id = 10
        self.title = "Pricing Tiers"
        self.status = "COMPLETED"
        self.task_id = "abc"
        self.results_json = {"winner": "tier_b"}
        self.created_at = "2026-08-07T20:00:00+00:00"


class _Project:
    def __init__(self) -> None:
        self.id = 10


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, decisions: list | None = None) -> None:
        self.decisions = decisions if decisions is not None else [_Decision()]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([_Project()])
        if name == "Decision":
            return _FakeQuery(self.decisions)
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import decisions as dec_mod

    db = session if session is not None else _FakeSession()
    return dec_mod.export_decisions(
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


def test_export_decisions_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="decisions-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "id,project_id,title,status,task_id,created_at,result_json" in body
    assert "1,10,Pricing Tiers,COMPLETED,abc,2026-08-07T20:00:00+00:00" in body


def test_export_decisions_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"title": "Pricing Tiers"' in body


def test_export_decisions_empty_project_returns_header_only() -> None:
    session = _FakeSession(decisions=[])
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "id,project_id,title,status,task_id,created_at,result_json" in body
    assert "1,10,Pricing Tiers" not in body


def test_export_decisions_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            name = getattr(model, "__name__", "")
            if name == "Project":
                return _FakeQuery([])
            return _FakeQuery(self.decisions)

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
