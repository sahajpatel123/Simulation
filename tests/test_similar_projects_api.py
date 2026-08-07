"""Route-level tests for the /projects/{id}/similar-projects endpoint."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Project:
    def __init__(self, project_id: int = 1, tags: list | None = None) -> None:
        self.id = project_id
        self.title = f"Project {project_id}"
        self.tags = tags if tags is not None else ["saas", "india"]


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
    def __init__(self, projects: list | None = None) -> None:
        self.projects = projects if projects is not None else [_Project(1)]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery(self.projects)
        return _FakeQuery([])


def _call_route(*, project_id: int = 1, session: _FakeSession | None = None):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.get_similar_projects(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_get_similar_projects_returns_list() -> None:
    session = _FakeSession([_Project(1), _Project(2)])
    result = _call_route(session=session)

    assert result["project_id"] == 1
    assert len(result["similar"]) == 1
    assert result["similar"][0]["project_id"] == 2


def test_get_similar_projects_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            return _FakeQuery([])

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
