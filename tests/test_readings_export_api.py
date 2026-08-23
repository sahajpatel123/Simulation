"""Route-level tests for the /projects/{id}/readings/export endpoint."""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Project:
    def __init__(self) -> None:
        self.id = 10
        self.readings_json = (
            '{"readings": [{"label": "WHAT IT IS", "body": "A lean tool"}],'
            ' "ledger": {"deck_line": "Small desk tool"}}'
        )


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
    return proj_mod.export_readings(
        project_id=project_id,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _call_count_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_readings_count(
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


def test_export_readings_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="readings-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "project_id,10" in body
    assert "index,label,body" in body
    assert "1,WHAT IT IS,A lean tool" in body
    assert "deck_line,Small desk tool" in body
    assert "user_id,42" in body


def test_export_readings_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"readings"' in body
    assert '"ledger"' in body
    assert "A lean tool" in body
    assert "Small desk tool" in body


def test_export_readings_format_json_normalizes_legacy_array() -> None:
    class LegacyProject(_Project):
        def __init__(self) -> None:
            super().__init__()
            self.id = 11
            self.readings_json = '[{"label": "WHAT IT IS", "body": "Lean"}]'

    resp = _call_route(
        project_id=11,
        format="json",
        session=_FakeSession(LegacyProject()),
    )

    body = _body(resp).decode("utf-8")
    assert '"project_id": 11' in body
    assert '"readings"' in body
    assert '"WHAT IT IS"' in body
    assert '"ledger": {}' in body


def test_export_readings_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            return _FakeQuery([])

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404


def test_export_readings_count_returns_csv() -> None:
    resp = _call_count_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="readings-count-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "project_id,readings_count" in body
    assert "10,1" in body
    assert "user_id,42" in body


def test_export_readings_count_format_json_returns_payload() -> None:
    resp = _call_count_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"readings_count": 1' in body


def test_export_readings_count_counts_normalized_readings() -> None:
    class TwoReadingProject(_Project):
        def __init__(self) -> None:
            super().__init__()
            self.id = 12
            self.readings_json = (
                '[{"label": "WHAT IT IS", "body": "Lean"},'
                ' {"label": "HIDDEN TENSION", "body": "No pricing"}]'
            )

    resp = _call_count_route(
        project_id=12,
        session=_FakeSession(TwoReadingProject()),
    )

    body = _body(resp).decode("utf-8")
    assert "12,2" in body


def test_export_readings_count_ignores_blank_entries() -> None:
    class MixedProject(_Project):
        def __init__(self) -> None:
            super().__init__()
            self.id = 14
            self.readings_json = (
                '{"readings": [{"label": "WHAT IT IS", "body": "Lean"},'
                ' {"label": " ", "body": ""}, {"label": "", "body": ""},'
                ' "junk", {"label": "HIDDEN TENSION", "body": ""}],'
                ' "ledger": {"deck_line": "Small desk tool"}}'
            )

    csv_resp = _call_count_route(
        project_id=14,
        session=_FakeSession(MixedProject()),
    )
    json_resp = _call_count_route(
        project_id=14,
        format="json",
        session=_FakeSession(MixedProject()),
    )

    csv_body = _body(csv_resp).decode("utf-8")
    json_body = _body(json_resp).decode("utf-8")
    assert "14,2" in csv_body
    assert '"readings_count": 2' in json_body


def test_export_readings_format_json_drops_blank_entries() -> None:
    class MixedProject(_Project):
        def __init__(self) -> None:
            super().__init__()
            self.id = 15
            self.readings_json = (
                '[{"label": "WHAT IT IS", "body": "Lean"},'
                ' {"label": " ", "body": ""}]'
            )

    resp = _call_route(
        project_id=15,
        format="json",
        session=_FakeSession(MixedProject()),
    )

    body = _body(resp).decode("utf-8")
    payload = json.loads(body)
    assert payload["readings"] == [{"label": "WHAT IT IS", "body": "Lean"}]


def test_export_readings_count_tolerates_malformed_json() -> None:
    class EmptyReadingsProject(_Project):
        def __init__(self) -> None:
            super().__init__()
            self.id = 13
            self.readings_json = "{not valid json"

    resp = _call_count_route(
        project_id=13,
        session=_FakeSession(EmptyReadingsProject()),
    )

    body = _body(resp).decode("utf-8")
    assert "13,0" in body


def test_export_readings_count_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            return _FakeQuery([])

    with pytest.raises(HTTPException) as exc:
        _call_count_route(session=NoProjectSession())
    assert exc.value.status_code == 404


def test_export_readings_count_invalid_format_rejected_with_422() -> None:
    from app.api.v1 import projects as proj_mod
    from app.core.deps import get_current_user, get_db

    mini_app = FastAPI()
    mini_app.include_router(proj_mod.router)
    mini_app.dependency_overrides[get_db] = lambda: _FakeSession()
    mini_app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": 42}
    )()

    with TestClient(mini_app) as client:
        resp = client.get(
            "/projects/10/readings-count/export",
            params={"format": "xlsx"},
        )

    assert resp.status_code == 422
