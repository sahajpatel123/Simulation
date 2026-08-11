"""Route-level tests for ``GET /projects/{id}/go-no-go/export``."""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.go_no_go import GoNoGoOut


def _payload() -> GoNoGoOut:
    return GoNoGoOut(
        project_id=10,
        latest_simulation_id=7,
        go_no_go_score=82,
        verdict="GO",
        verdict_label="Signals support launch",
        pillars=[
            {
                "key": "readiness",
                "label": "Launch readiness",
                "score": 88,
                "verdict": "STRONG",
                "weight": 0.2,
                "evidence": [
                    "Launch-checklist readiness 88/100 (READY)",
                ],
                "summary": "Launch signals are ready",
            }
        ],
        gates=[
            {
                "id": "readiness_gate",
                "label": "Launch readiness is strong enough",
                "evaluated": True,
                "passed": True,
                "detail": "Launch-checklist readiness must reach 80/100",
            }
        ],
        strengths=["Readiness is strong"],
        risks=["Coverage is thin"],
        top_actions=["Close the top launch-checklist gap"],
        narrative="Signals support launch (go/no-go 82/100).",
        meta={"total_pillars": 1},
    )


def _call_route(
    *,
    format: str = "csv",
    project_id: int = 10,
    monkeypatch: pytest.MonkeyPatch,
    payload: GoNoGoOut | None = None,
):
    from app.api.v1 import projects as projects_mod

    monkeypatch.setattr(
        projects_mod,
        "get_go_no_go",
        lambda project_id, db, current_user: (
            payload if payload is not None else _payload()
        ),
    )
    return projects_mod.export_go_no_go(
        project_id=project_id,
        format=format,
        db=object(),
        current_user=type("U", (), {"id": 42})(),
    )


async def _stream_bytes(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response) -> bytes:
    return asyncio.run(_stream_bytes(response))


def test_export_go_no_go_returns_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch=monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert 'filename="go-no-go-10.csv"' in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8")
    assert "user_id,42" in text
    assert "section,Go/No-Go Summary" in text
    assert "go_no_go_score,82" in text
    assert "section,Pillars" in text
    assert "readiness,Launch readiness,88,STRONG,0.2" in text
    assert "section,Launch Gates" in text
    assert "readiness_gate,Launch readiness is strong enough,True,True" in text
    assert "section,Top Actions" in text
    assert "Close the top launch-checklist gap" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_go_no_go_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(format="json", monkeypatch=monkeypatch)

    assert response.media_type == "application/json; charset=utf-8"
    assert 'filename="go-no-go-10.json"' in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response).decode("utf-8")
    parsed = json.loads(body)
    assert parsed["metadata"]["project_id"] == 10
    assert parsed["go_no_go"]["go_no_go_score"] == 82
    assert parsed["go_no_go"]["verdict"] == "GO"
    assert parsed["go_no_go"]["top_actions"][0] == (
        "Close the top launch-checklist gap"
    )


def test_export_go_no_go_metadata_uses_format_version_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as projects_mod

    monkeypatch.setattr(projects_mod, "FORMAT_VERSION", "9")

    json_response = _call_route(format="json", monkeypatch=monkeypatch)
    parsed = json.loads(_body(json_response).decode("utf-8"))
    assert parsed["metadata"]["format_version"] == "9"

    csv_response = _call_route(monkeypatch=monkeypatch)
    assert b"format_version,9" in _body(csv_response)


def test_export_go_no_go_accepts_uppercase_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(format="JSON", monkeypatch=monkeypatch)

    assert response.media_type == "application/json; charset=utf-8"
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["go_no_go"]["go_no_go_score"] == 82


def test_export_go_no_go_rejects_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(format="xml", monkeypatch=monkeypatch)
    assert exc.value.status_code == 400
    assert "xml" in exc.value.detail


def test_export_go_no_go_forwards_missing_project_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import projects as projects_mod

    def _not_found(project_id, db, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(projects_mod, "get_go_no_go", _not_found)

    with pytest.raises(HTTPException) as exc:
        projects_mod.export_go_no_go(
            project_id=10,
            format="csv",
            db=object(),
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 404
