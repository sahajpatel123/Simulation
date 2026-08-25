"""Route-level tests for ``POST /projects/compare/export``."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.project_comparison import ProjectCompareRequest


class _FakeProject:
    def __init__(self, project_id: int) -> None:
        self.id = project_id
        self.title = f"Project {project_id}"
        self.status = "ACTIVE"
        self.brief_completed_at = datetime.now(UTC)


class _FakeSimulation:
    def __init__(self) -> None:
        self.confidence_score = 0.62
        self.results_json = {
            "population_weighted_conversion": 0.04,
            "product_type_detected": "saas",
            "primary_failure_domain": "pricing",
            "domain_findings": [],
        }


class _FakeAssumption:
    def __init__(self) -> None:
        self.id = 1
        self.sensitivity = "HIGH"
        self.specificity_score = 0.9
        self.impact_score = 8.0
        self.is_hidden = False


class _FakeQuery:
    def __init__(
        self,
        *,
        first: Any = None,
        count: int = 0,
        all_items: list[Any] | None = None,
    ) -> None:
        self.first_item = first
        self.count_value = count
        self.all_items = all_items if all_items is not None else []

    def join(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self.first_item

    def count(self) -> int:
        return self.count_value

    def all(self) -> list[Any]:
        return self.all_items


class _FakeSession:
    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery(first=_FakeSimulation(), count=2)
        if name == "Assumption":
            return _FakeQuery(count=5, all_items=[_FakeAssumption()])
        if name == "Outcome":
            return _FakeQuery(count=1)
        if name == "Decision":
            return _FakeQuery(count=0)
        return _FakeQuery()


def _call_route(
    *,
    format: str = "csv",
    project_ids: list[int] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    from app.api.v1 import projects as projects_mod

    monkeypatch.setattr(
        projects_mod,
        "get_owned_project",
        lambda db, user_id, project_id: _FakeProject(project_id),
    )
    return projects_mod.export_project_comparison(
        payload=ProjectCompareRequest(
            project_ids=project_ids or [1, 2]
        ),
        format=format,
        db=_FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def test_export_project_comparison_returns_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch=monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert 'filename="project-comparison.csv"' in response.headers[
        "Content-Disposition"
    ]
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "user_id,42" in text
    assert "section,Project Comparison Summary" in text
    assert "section,Projects Compared" in text
    assert "section,Dimension Comparison" in text
    assert "Project 1" in text
    assert "Project 2" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_project_comparison_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(format="json", monkeypatch=monkeypatch)

    assert response.media_type == "application/json; charset=utf-8"
    assert 'filename="project-comparison.json"' in response.headers[
        "Content-Disposition"
    ]
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 1
    assert parsed["metadata"]["format_version"] == "1"
    comp = parsed["project_comparison"]
    assert len(comp["projects"]) == 2
    assert len(comp["dimensions"]) == 10
    assert comp["projects"][0]["title"] == "Project 1"


def test_export_project_comparison_returns_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(format="md", monkeypatch=monkeypatch)

    assert response.media_type == "text/markdown; charset=utf-8"
    assert 'filename="project-comparison.md"' in response.headers[
        "Content-Disposition"
    ]
    body = _body(response).decode("utf-8")
    assert body.startswith("# Project Comparison")
    assert "## Verdict" in body
    assert "## Dimension Comparison" in body


def test_export_project_comparison_accepts_uppercase_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(format="JSON", monkeypatch=monkeypatch)
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["project_comparison"]["summary"]["verdict"] in {
        "A_LEADS",
        "B_LEADS",
        "TIE",
    }


def test_export_project_comparison_rejects_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(format="pdf", monkeypatch=monkeypatch)
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail


def test_export_project_comparison_forwards_missing_project_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as projects_mod

    def _not_found(db: Any, user_id: int, project_id: int) -> Any:
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(projects_mod, "get_owned_project", _not_found)

    with pytest.raises(HTTPException) as exc:
        projects_mod.export_project_comparison(
            payload=ProjectCompareRequest(project_ids=[1, 2]),
            format="csv",
            db=_FakeSession(),
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 404
