"""Tests for the coverage-gaps export helper and route."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.project import ProjectCoverageGapsOut
from app.simulation.coverage_gaps_export import (
    coverage_gaps_to_csv,
    coverage_gaps_to_json,
)


def _payload() -> ProjectCoverageGapsOut:
    return ProjectCoverageGapsOut(
        project_id=7,
        project_title="Pricing idea",
        covered_categories=["Pricing", "Trust"],
        missing_categories=["Market", "Retention"],
        sensitivity_breakdown={"HIGH": 2, "MEDIUM": 1},
        covered_cluster_count=3,
        missing_architect_count=2,
        total_assumption_count=3,
        narrative="The project has not explored Retention.",
        key_signals=[
            {
                "label": "Retention untested",
                "value": "missing",
                "severity": "critical",
                "display": "Retention assumptions are missing",
            }
        ],
    )


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def test_csv_renders_summary_categories_and_signals() -> None:
    csv_text = coverage_gaps_to_csv(
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
    assert "section,Coverage Gaps Summary" in csv_text
    assert "project_title,Pricing idea" in csv_text
    assert "total_assumption_count,3" in csv_text
    assert "sensitivity_breakdown,HIGH=2; MEDIUM=1" in csv_text
    assert "section,Covered Categories" in csv_text
    assert "1,Pricing" in csv_text
    assert "2,Trust" in csv_text
    assert "section,Missing Categories" in csv_text
    assert "1,Market" in csv_text
    assert "2,Retention" in csv_text
    assert "section,Sensitivity Breakdown" in csv_text
    assert "HIGH,2" in csv_text
    assert "MEDIUM,1" in csv_text
    assert "section,Key Signals" in csv_text
    assert "Retention untested,missing,critical" in csv_text
    assert "Retention assumptions are missing" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = coverage_gaps_to_csv(
        ProjectCoverageGapsOut(),
    )

    assert "section,Coverage Gaps Summary" in csv_text
    assert "section,Covered Categories" in csv_text
    assert "section,Missing Categories" in csv_text
    assert "section,Sensitivity Breakdown" in csv_text
    assert "section,Key Signals" in csv_text
    assert "index,category" in csv_text
    assert "label,value,severity,display" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = coverage_gaps_to_csv(
        {
            "project_id": 7,
            "project_title": "Pricing idea",
            "covered_categories": [],
            "missing_categories": [],
            "sensitivity_breakdown": {},
            "covered_cluster_count": 0,
            "missing_architect_count": 0,
            "total_assumption_count": 0,
            "narrative": "",
            "key_signals": [],
        }
    )

    assert "project_id,7" in csv_text
    assert "section,Covered Categories" in csv_text
    assert "section,Missing Categories" in csv_text
    assert "section,Sensitivity Breakdown" in csv_text
    assert "section,Key Signals" in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    payload = ProjectCoverageGapsOut(
        project_id=1,
        project_title='=HYPERLINK("http://evil")',
        covered_categories=["+1+1"],
        missing_categories=["@SUM(A1:A2)"],
        sensitivity_breakdown={"HIGH": 2},
        covered_cluster_count=1,
        missing_architect_count=0,
        total_assumption_count=2,
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
    csv_text = coverage_gaps_to_csv(
        payload,
        metadata={
            "generated_at": "=NOW()",
            "user_id": 42,
            "format_version": "1",
            "project_id": 1,
        },
    )

    assert "'=HYPERLINK" in csv_text
    assert "'+1+1" in csv_text
    assert "'@SUM(A1:A2)" in csv_text
    assert "'-2+3" in csv_text
    assert "'=cmd" in csv_text
    assert "'=NOW()" in csv_text


def test_csv_summary_breakdown_formula_key_is_guarded() -> None:
    payload = ProjectCoverageGapsOut(
        project_id=1,
        project_title="Pricing idea",
        covered_categories=[],
        missing_categories=[],
        sensitivity_breakdown={"=cmd": 1},
        covered_cluster_count=0,
        missing_architect_count=0,
        total_assumption_count=1,
        narrative="",
        key_signals=[],
    )
    csv_text = coverage_gaps_to_csv(payload)

    assert "'=cmd=1" in csv_text


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def test_json_does_not_escape_formula_like_text() -> None:
    json_text = coverage_gaps_to_json(
        {
            "project_id": 1,
            "project_title": '=HYPERLINK("http://evil")',
            "covered_categories": ["+1+1"],
            "missing_categories": ["@SUM(A1:A2)"],
            "sensitivity_breakdown": {"HIGH": 2},
            "covered_cluster_count": 1,
            "missing_architect_count": 0,
            "total_assumption_count": 2,
            "narrative": "-2+3",
            "key_signals": [],
        },
        metadata={"generated_at": "=NOW()"},
    )

    assert '"generated_at": "=NOW()"' in json_text
    assert '"project_title": "=HYPERLINK(\\"http://evil\\")"' in json_text
    assert '"covered_categories": [\n      "+1+1"\n    ]' in json_text
    assert '"missing_categories": [\n      "@SUM(A1:A2)"\n    ]' in json_text
    assert '"-2+3"' in json_text


def test_json_renders_metadata_and_payload() -> None:
    json_text = coverage_gaps_to_json(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "project_id": 7,
        },
    )

    assert '"metadata"' in json_text
    assert '"coverage_gaps"' in json_text
    assert '"project_title"' in json_text
    assert '"Pricing idea"' in json_text
    assert '"Retention"' in json_text


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
    payload: ProjectCoverageGapsOut | None = None,
):
    proj_mod = _import_projects_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_coverage_gaps(**kwargs: object) -> ProjectCoverageGapsOut:
        return fake_payload

    monkeypatch.setattr(
        proj_mod,
        "get_project_coverage_gaps",
        _fake_get_coverage_gaps,
    )
    return proj_mod.export_project_coverage_gaps(
        project_id=project_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    proj_mod = _import_projects_module()

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/coverage-gaps/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/projects/{project_id}/coverage-gaps/export"]


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="coverage-gaps-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Coverage Gaps Summary" in body
    assert "total_assumption_count,3" in body
    assert "section,Covered Categories" in body
    assert "1,Pricing" in body
    assert "section,Missing Categories" in body
    assert "2,Retention" in body
    assert "section,Sensitivity Breakdown" in body
    assert "section,Key Signals" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="coverage-gaps-1.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"coverage_gaps"' in body
    assert '"project_title"' in body
    assert '"Retention"' in body


def test_export_route_filename_includes_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_resp = _call_route(monkeypatch, project_id=42)
    assert 'filename="coverage-gaps-42.csv"' in csv_resp.headers["Content-Disposition"]

    json_resp = _call_route(monkeypatch, project_id=42, format="json")
    assert 'filename="coverage-gaps-42.json"' in json_resp.headers["Content-Disposition"]


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
    """An unsupported format must not pay for the coverage aggregation."""
    proj_mod = _import_projects_module()
    calls: list[object] = []

    def _forbidden_get(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(proj_mod, "get_project_coverage_gaps", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        proj_mod.export_project_coverage_gaps(
            project_id=1,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
