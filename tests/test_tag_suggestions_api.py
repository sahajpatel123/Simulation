"""Route-level tests for the /projects/{id}/tag-suggestions endpoint."""
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
    def __init__(self) -> None:
        self.id = 10
        self.title = "AI Sim"
        self.description = "A simulation engine for founders"
        self.tags = ["sim"]


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
    max_tags: int = 5,
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.get_tag_suggestions(
        project_id=project_id,
        max_tags=max_tags,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_get_tag_suggestions_returns_list() -> None:
    result = _call_route()

    assert result["project_id"] == 10
    assert isinstance(result["tags"], list)
    assert "sim" not in result["tags"]
    assert "founders" in result["tags"]


def test_get_tag_suggestions_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            return _FakeQuery([])

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
