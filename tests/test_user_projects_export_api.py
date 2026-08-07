"""Route-level tests for the /me/projects/export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Project:
    def __init__(self) -> None:
        self.id = 1
        self.title = "TheCee"
        self.status = "DRAFT"
        self.intake_mode = "IDEA"
        self.is_archived = False
        self.created_at = "2026-08-08T04:00:00+00:00"


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, projects: list | None = None) -> None:
        self.projects = projects if projects is not None else [_Project()]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery(self.projects)
        return _FakeQuery([])


def _call_route(*, format: str = "csv", session: _FakeSession | None = None):
    from app.api.v1 import users as user_mod

    db = session if session is not None else _FakeSession()
    return user_mod.export_my_projects(
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


def test_export_my_projects_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'attachment; filename="my-projects.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "project_id,title,status,intake_mode" in body
    assert "1,TheCee,DRAFT,IDEA,False" in body
    assert "user_id,42" in body


def test_export_my_projects_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"projects"' in body
    assert '"project_id": 1' in body
    assert '"title": "TheCee"' in body


def test_export_my_projects_empty_returns_header_only() -> None:
    resp = _call_route(session=_FakeSession(projects=[]))

    body = _body(resp).decode("utf-8")
    assert "project_id,title,status,intake_mode" in body
    assert "1,TheCee" not in body
