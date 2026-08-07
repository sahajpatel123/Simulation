"""Tests for the project-health export helper and route."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.project import ProjectHealthOut
from app.simulation.project_health_export import (
    project_health_to_csv,
    project_health_to_json,
)


def _payload() -> ProjectHealthOut:
    return ProjectHealthOut(
        project_health_score=85,
        verdict="HEALTHY",
        score_breakdown={
            "sim_confidence": 30,
            "zero_critical_findings": 20,
            "zero_pending_decisions": 10,
            "has_outcome": 10,
            "zero_weak_links": 15,
        },
        narrative=(
            "Project health is 85/100 (healthy). Contributions: "
            "sim confidence +30, zero critical findings +20, "
            "zero pending decisions +10, has outcome +10, "
            "zero weak links +15."
        ),
        key_signals=[
            {
                "label": "project_health_score",
                "value": 85,
                "severity": "ok",
                "display": "Project health: 85/100",
            }
        ],
    )


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def test_csv_renders_summary_breakdown_and_signals() -> None:
    csv_text = project_health_to_csv(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "project_id": 7,
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "project_id,7" in csv_text
    assert "section,Project Health Summary" in csv_text
    assert "project_health_score,85" in csv_text
    assert "verdict,HEALTHY" in csv_text
    assert "zero_critical_findings=20" in csv_text
    assert "Project health is 85/100" in csv_text
    assert "section,Score Breakdown" in csv_text
    assert "component,points" in csv_text
    assert "has_outcome,10" in csv_text
    assert "section,Key Signals" in csv_text
    assert "project_health_score,85,ok" in csv_text
    assert "Project health: 85/100" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = project_health_to_csv(ProjectHealthOut())

    assert "section,Project Health Summary" in csv_text
    assert "section,Score Breakdown" in csv_text
    assert "section,Key Signals" in csv_text
    assert "key,value" in csv_text
    assert "component,points" in csv_text
    assert "label,value,severity,display" in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    payload = ProjectHealthOut(
        project_health_score=1,
        verdict="=AT_RISK",
        score_breakdown={"=component": -1},
        narrative="-2+3",
        key_signals=[
            {
                "label": "=cmd",
                "value": "=NOW()",
                "severity": "critical",
                "display": "+1",
            }
        ],
    )
    csv_text = project_health_to_csv(
        payload,
        metadata={
            "generated_at": "=NOW()",
            "user_id": 42,
            "format_version": "1",
            "project_id": 1,
        },
    )

    assert "'=AT_RISK" in csv_text
    assert "'=component=-1" in csv_text
    assert "'-2+3" in csv_text
    assert "'=cmd" in csv_text
    assert "'=NOW()" in csv_text


def test_csv_neutralizes_formula_after_leading_whitespace() -> None:
    """Formula chars hidden after leading whitespace are still neutralized."""
    payload = ProjectHealthOut(
        project_health_score=1,
        verdict=" =AT_RISK",
        score_breakdown={},
        narrative="\t=SUM(1,2)",
        key_signals=[
            {
                "label": "  @cmd",
                "value": 1,
                "severity": "ok",
                "display": " +NOW()",
            }
        ],
    )
    csv_text = project_health_to_csv(
        payload,
        metadata={
            "generated_at": "\r=cmd",
            "user_id": 42,
            "format_version": "1",
            "project_id": 1,
        },
    )

    assert "' =AT_RISK" in csv_text
    assert "'\t=SUM(1,2)" in csv_text
    assert "'  @cmd" in csv_text
    assert "' +NOW()" in csv_text
    assert "'\r=cmd" in csv_text


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def test_json_renders_metadata_and_payload() -> None:
    json_text = project_health_to_json(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "project_id": 7,
        },
    )

    assert '"metadata"' in json_text
    assert '"project_health"' in json_text
    assert '"verdict"' in json_text
    assert '"HEALTHY"' in json_text
    assert '"score_breakdown"' in json_text
    assert '"key_signals"' in json_text


def test_json_does_not_escape_formula_like_text() -> None:
    json_text = project_health_to_json(
        {
            "project_health_score": 1,
            "verdict": "=AT_RISK",
            "score_breakdown": {},
            "narrative": "-2+3",
            "key_signals": [],
        },
        metadata={"generated_at": "=NOW()"},
    )

    assert '"generated_at": "=NOW()"' in json_text
    assert '"verdict": "=AT_RISK"' in json_text
    assert '"-2+3"' in json_text


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _import_projects_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import projects as proj_mod

    return proj_mod


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_id: int = 1,
    format: str = "csv",
    payload: ProjectHealthOut | None = None,
):
    proj_mod = _import_projects_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_project_health(**kwargs: object) -> ProjectHealthOut:
        return fake_payload

    monkeypatch.setattr(
        proj_mod,
        "get_project_health",
        _fake_get_project_health,
    )
    return proj_mod.export_project_health(
        project_id=project_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    proj_mod = _import_projects_module()

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/health/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path[
        "/projects/{project_id}/health/export"
    ]


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="health-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Project Health Summary" in body
    assert "project_health_score,85" in body
    assert "section,Score Breakdown" in body
    assert "section,Key Signals" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="health-1.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"project_health"' in body
    assert '"HEALTHY"' in body


def test_export_route_filename_includes_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_resp = _call_route(monkeypatch, project_id=42)
    assert 'filename="health-42.csv"' in csv_resp.headers[
        "Content-Disposition"
    ]

    json_resp = _call_route(monkeypatch, project_id=42, format="json")
    assert 'filename="health-42.json"' in json_resp.headers[
        "Content-Disposition"
    ]


def test_export_route_rejects_unknown_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported format must not pay for the health aggregation."""
    proj_mod = _import_projects_module()
    calls: list[object] = []

    def _forbidden_get(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError(
            "payload builder should not run for bad format"
        )

    monkeypatch.setattr(
        proj_mod,
        "get_project_health",
        _forbidden_get,
    )

    with pytest.raises(HTTPException) as exc_info:
        proj_mod.export_project_health(
            project_id=1,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
