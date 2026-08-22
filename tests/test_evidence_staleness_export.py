"""Route and serialization tests for evidence-freshness exports.

Covers CSV, JSON, and Markdown rendering of the freshness payload,
format validation, formula-injection guarding, and Markdown cell escaping.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.evidence_staleness import EvidenceStalenessOut
from app.simulation.evidence_staleness import build_evidence_staleness

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _payload() -> EvidenceStalenessOut:
    raw = build_evidence_staleness(
        [
            {
                "id": 1,
                "text": "=SUM(A1:A2)",
                "category": "Pricing",
                "sensitivity": "HIGH",
            },
            {
                "id": 2,
                "text": "Never|tested claim",
                "category": "Retention",
                "sensitivity": "LOW",
            },
            {
                "id": 3,
                "text": "Fresh signal",
                "category": "Demand",
                "sensitivity": "MEDIUM",
            },
        ],
        [
            {
                "assumption_id": 1,
                "created_at": NOW - timedelta(days=90),
            },
            {
                "assumption_id": 3,
                "created_at": NOW - timedelta(days=2),
            },
        ],
        project_id=7,
        now=NOW,
    )
    return EvidenceStalenessOut.model_validate(raw)


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    format: str = "csv",
    fresh_days: int = 14,
    aging_days: int = 45,
    payload: EvidenceStalenessOut | None = None,
) -> Any:
    from app.api.v1 import assumption_evidence as ev_mod

    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        ev_mod,
        "get_evidence_freshness",
        lambda **kwargs: fake_payload,
    )
    return ev_mod.export_evidence_freshness(
        project_id=7,
        format=format,
        fresh_days=fresh_days,
        aging_days=aging_days,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/evidence-freshness/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_returns_csv_with_queue_and_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="evidence-freshness-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Evidence Freshness Summary" in text
    assert "section,Re-test Queue" in text
    assert "actionable_count,2" in text
    # Never-tested leads the queue; stale HIGH-sensitivity follows.
    queue = text.split("section,Re-test Queue")[1]
    assert queue.index("2,Never") < queue.index("1,'=SUM")
    # Formula guard neutralises the spreadsheet-formula assumption text.
    assert "'=SUM(A1:A2)" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_route_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["format_version"] == "1"
    freshness = parsed["evidence_freshness"]
    assert freshness["project_id"] == 7
    assert freshness["summary"]["stale_count"] == 1
    assert freshness["rows"][0]["freshness"] == "NEVER_TESTED"


def test_export_route_returns_markdown_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    body = _body(response).decode("utf-8")
    assert "# Evidence Freshness" in body
    assert "| Fresh share of tested | 50.0% |" in body
    assert "## Re-test Queue" in body
    # Pipe inside assumption text cannot break the table.
    assert "Never\\|tested claim" in body
    assert "- Design a first experiment for" in body


def test_export_rejects_unknown_format_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list[dict[str, Any]] = []

    def forbidden_freshness(**kwargs: Any) -> EvidenceStalenessOut:
        calls.append(kwargs)
        raise AssertionError("payload should not build for an invalid format")

    monkeypatch.setattr(ev_mod, "get_evidence_freshness", forbidden_freshness)
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail
    assert calls == []


def test_export_rejects_inverted_windows_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list[dict[str, Any]] = []

    def forbidden_freshness(**kwargs: Any) -> EvidenceStalenessOut:
        calls.append(kwargs)
        raise AssertionError("payload should not build for bad windows")

    monkeypatch.setattr(ev_mod, "get_evidence_freshness", forbidden_freshness)
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, fresh_days=45, aging_days=45)

    assert exc_info.value.status_code == 400
    assert calls == []
