"""Route-level tests for the /projects/{id}/prototypes/export endpoint."""
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


class _Prototype:
    def __init__(self, prototype_id: int = 1) -> None:
        self.id = prototype_id
        self.project_id = 10
        self.html_content = "<html></html>"
        self.funnel_graph_json = '{"nodes": []}'
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
    def __init__(self, prototypes: list | None = None) -> None:
        self.prototypes = prototypes if prototypes is not None else [_Prototype()]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([_Project()])
        if name == "Prototype":
            return _FakeQuery(self.prototypes)
        return _FakeQuery([])


def _call_route(*, project_id: int = 10, session: _FakeSession | None = None):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_prototypes(
        project_id=project_id,
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


def test_export_prototypes_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="prototypes-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "id,project_id,html_content,funnel_graph_json,created_at" in body
    assert "<html></html>" in body
    assert "user_id,42" in body


def test_export_prototypes_empty_returns_header_only() -> None:
    session = _FakeSession(prototypes=[])
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "id,project_id,html_content,funnel_graph_json,created_at" in body
    assert "<html></html>" not in body


def test_export_prototypes_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            name = getattr(model, "__name__", "")
            if name == "Project":
                return _FakeQuery([])
            return _FakeQuery(self.prototypes)

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
