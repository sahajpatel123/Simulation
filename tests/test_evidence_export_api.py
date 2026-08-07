"""Route-level tests for the /projects/{id}/evidence/export endpoint."""
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


class _Evidence:
    def __init__(self, evidence_id: int = 1) -> None:
        self.id = evidence_id
        self.project_id = 10
        self.assumption_id = 3
        self.method = "interview"
        self.result = "PASS"
        self.observed_metric = 0.62
        self.notes = "validated"
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
    def __init__(self, evidence: list | None = None) -> None:
        self.evidence = evidence if evidence is not None else [_Evidence()]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([_Project()])
        if name == "AssumptionEvidence":
            return _FakeQuery(self.evidence)
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_evidence(
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


def test_export_evidence_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="evidence-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "id,project_id,assumption_id,method,result" in body
    assert "1,10,3,interview,PASS,0.62,validated" in body
    assert "user_id,42" in body


def test_export_evidence_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"project_id": 10' in body
    assert '"method": "interview"' in body


def test_export_evidence_empty_returns_header_only() -> None:
    session = _FakeSession(evidence=[])
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "id,project_id,assumption_id,method,result" in body
    assert "1,10,3,interview,PASS" not in body


def test_export_evidence_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            name = getattr(model, "__name__", "")
            if name == "Project":
                return _FakeQuery([])
            return _FakeQuery(self.evidence)

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404
