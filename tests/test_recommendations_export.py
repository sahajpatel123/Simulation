"""Tests for the recommendations export helper and route."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.project import RecommendationsDigestOut
from app.simulation.recommendations_export import (
    recommendations_to_csv,
    recommendations_to_json,
)


def _payload() -> RecommendationsDigestOut:
    return RecommendationsDigestOut(
        recommendation_count=2,
        critical_failure_count=1,
        quick_win_count=1,
        top_recommendations=[
            {
                "source": "intervention",
                "title": "Quick win: Fix onboarding copy",
                "severity": "LOW",
                "impact_score": None,
                "priority_score": 0.92,
                "description": "Reword the first screen to match buyer language.",
            },
            {
                "source": "premortem",
                "title": "Critical: Pricing anchor may repel price-sensitive clusters",
                "severity": "CRITICAL",
                "impact_score": 9.5,
                "priority_score": None,
                "description": "Test a mid-tier anchor before launch.",
            },
        ],
        narrative=(
            "2 recommendation(s) composed from premortem + interventions. "
            "1 critical failure(s) and 1 quick win(s) surfaced."
        ),
        key_signals=[
            {
                "label": "recommendation_count",
                "value": 2,
                "severity": "ok",
                "display": "2 recommendation(s) ready",
            }
        ],
    )


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------


def test_csv_renders_summary_recommendations_and_signals() -> None:
    csv_text = recommendations_to_csv(
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
    assert "section,Recommendations Summary" in csv_text
    assert "recommendation_count,2" in csv_text
    assert "critical_failure_count,1" in csv_text
    assert "quick_win_count,1" in csv_text
    assert "2 recommendation(s) composed" in csv_text
    assert "section,Top Recommendations" in csv_text
    assert "rank,source,title,severity,impact_score,priority_score,description" in csv_text
    assert "1,intervention,Quick win: Fix onboarding copy,LOW,,0.92" in csv_text
    assert "2,premortem,Critical: Pricing anchor may repel price-sensitive clusters,CRITICAL,9.5," in csv_text
    assert "section,Key Signals" in csv_text
    assert "recommendation_count,2,ok,2 recommendation(s) ready" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = recommendations_to_csv(RecommendationsDigestOut())

    assert "section,Recommendations Summary" in csv_text
    assert "section,Top Recommendations" in csv_text
    assert "section,Key Signals" in csv_text
    assert "key,value" in csv_text
    assert "rank,source,title,severity,impact_score,priority_score,description" in csv_text
    assert "label,value,severity,display" in csv_text


def test_csv_summary_project_id_falls_back_to_metadata() -> None:
    """The digest payload omits project_id; the summary should use the
    metadata block instead of rendering a blank project_id row.
    """
    csv_text = recommendations_to_csv(
        RecommendationsDigestOut(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "project_id": 17,
        },
    )

    assert csv_text.count("project_id,17") >= 2


def test_csv_handles_plain_dict_payload() -> None:
    """The helper is used with both Pydantic models and plain dicts."""
    csv_text = recommendations_to_csv(
        {
            "recommendation_count": 1,
            "critical_failure_count": 0,
            "quick_win_count": 1,
            "top_recommendations": [
                {
                    "source": "intervention",
                    "title": "Quick win: Tighten first-screen copy",
                    "severity": "LOW",
                    "impact_score": None,
                    "priority_score": 0.91,
                    "description": "Match buyer language on the landing page.",
                }
            ],
            "narrative": "One quick win ready to act on.",
            "key_signals": [
                {
                    "label": "quick_win_count",
                    "value": 1,
                    "severity": "ok",
                    "display": "1 quick win(s) ready",
                }
            ],
        }
    )

    assert "recommendation_count,1" in csv_text
    assert "1,intervention,Quick win: Tighten first-screen copy,LOW,,0.91" in csv_text
    assert "1 quick win(s) ready" in csv_text


def test_csv_skips_non_dict_rows() -> None:
    """Non-dict entries in the recommendation/signal lists must not crash
    the export and must not render garbage rows.
    """
    csv_text = recommendations_to_csv(
        {
            "recommendation_count": 1,
            "critical_failure_count": 0,
            "quick_win_count": 1,
            "top_recommendations": [
                {
                    "source": "intervention",
                    "title": "Only dict",
                    "severity": "LOW",
                    "impact_score": None,
                    "priority_score": 0.9,
                    "description": "Keep this one.",
                },
                "not-a-dict",
                None,
            ],
            "narrative": "One recommendation.",
            "key_signals": [
                {
                    "label": "recommendation_count",
                    "value": 1,
                    "severity": "ok",
                    "display": "1 ready",
                },
                42,
                None,
            ],
        }
    )

    assert "Only dict" in csv_text
    assert "not-a-dict" not in csv_text
    assert "1 ready" in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    payload = RecommendationsDigestOut(
        recommendation_count=1,
        top_recommendations=[
            {
                "source": "=cmd",
                "title": "-2+3",
                "severity": "LOW",
                "impact_score": 1,
                "priority_score": 1,
                "description": "=SUM(1,2)",
            }
        ],
        narrative="@cmd",
        key_signals=[
            {
                "label": "=NOW()",
                "value": "+1",
                "severity": "critical",
                "display": "  @display",
            }
        ],
    )
    csv_text = recommendations_to_csv(
        payload,
        metadata={
            "generated_at": "=NOW()",
            "user_id": 42,
            "format_version": "1",
            "project_id": 1,
        },
    )

    assert "'=cmd" in csv_text
    assert "'-2+3" in csv_text
    assert "'=SUM(1,2)" in csv_text
    assert "'@cmd" in csv_text
    assert "'=NOW()" in csv_text
    assert "'+1" in csv_text
    assert "'  @display" in csv_text


def test_csv_neutralizes_formula_after_leading_whitespace() -> None:
    payload = RecommendationsDigestOut(
        top_recommendations=[
            {
                "source": "intervention",
                "title": " =AT_RISK",
                "severity": "\t=SUM(1,2)",
                "impact_score": 1,
                "priority_score": 1,
                "description": " @cmd",
            }
        ],
    )
    csv_text = recommendations_to_csv(payload)

    assert "' =AT_RISK" in csv_text
    assert "'\t=SUM(1,2)" in csv_text
    assert "' @cmd" in csv_text


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def test_json_renders_metadata_and_payload() -> None:
    json_text = recommendations_to_json(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "project_id": 7,
        },
    )

    assert '"metadata"' in json_text
    assert '"recommendations"' in json_text
    assert '"recommendation_count"' in json_text
    assert '"top_recommendations"' in json_text
    assert '"critical_failure_count"' in json_text
    assert '"key_signals"' in json_text


def test_json_does_not_escape_formula_like_text() -> None:
    json_text = recommendations_to_json(
        {
            "recommendation_count": 1,
            "critical_failure_count": 0,
            "quick_win_count": 0,
            "top_recommendations": [
                {
                    "source": "intervention",
                    "title": "=AT_RISK",
                    "severity": "LOW",
                    "impact_score": None,
                    "priority_score": 0.9,
                    "description": "-2+3",
                }
            ],
            "narrative": "=NOW()",
            "key_signals": [],
        },
        metadata={"generated_at": "=NOW()"},
    )

    assert '"generated_at": "=NOW()"' in json_text
    assert '"title": "=AT_RISK"' in json_text
    assert '"-2+3"' in json_text
    assert '"narrative": "=NOW()"' in json_text


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
    payload: RecommendationsDigestOut | None = None,
):
    proj_mod = _import_projects_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_recommendations_digest(**kwargs: object) -> RecommendationsDigestOut:
        return fake_payload

    monkeypatch.setattr(
        proj_mod,
        "get_recommendations_digest",
        _fake_get_recommendations_digest,
    )
    return proj_mod.export_project_recommendations(
        project_id=project_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    proj_mod = _import_projects_module()

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/recommendations/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path[
        "/projects/{project_id}/recommendations/export"
    ]


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="recommendations-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Recommendations Summary" in body
    assert "recommendation_count,2" in body
    assert "section,Top Recommendations" in body
    assert "Quick win: Fix onboarding copy" in body
    assert "section,Key Signals" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="recommendations-1.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"recommendations"' in body
    assert '"critical_failure_count"' in body
    assert '"top_recommendations"' in body


def test_export_route_filename_includes_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_resp = _call_route(monkeypatch, project_id=42)
    assert 'filename="recommendations-42.csv"' in csv_resp.headers[
        "Content-Disposition"
    ]

    json_resp = _call_route(monkeypatch, project_id=42, format="json")
    assert 'filename="recommendations-42.json"' in json_resp.headers[
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
    """An unsupported format must not pay for the digest composition."""
    proj_mod = _import_projects_module()
    calls: list[object] = []

    def _forbidden_get(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError(
            "payload builder should not run for bad format"
        )

    monkeypatch.setattr(
        proj_mod,
        "get_recommendations_digest",
        _forbidden_get,
    )

    with pytest.raises(HTTPException) as exc_info:
        proj_mod.export_project_recommendations(
            project_id=1,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
