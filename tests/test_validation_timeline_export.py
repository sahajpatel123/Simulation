"""Route and serialization tests for validation-timeline exports.

Covers CSV, JSON, and Markdown rendering of the timeline payload
(events, progress snapshots, assumptions, milestones), format
validation, and formula-injection guarding.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.validation_timeline import AssumptionValidationTimelineOut


def _payload() -> AssumptionValidationTimelineOut:
    return AssumptionValidationTimelineOut.model_validate(
        {
            "project_id": 7,
            "total_assumptions": 2,
            "total_evidence_rows": 2,
            "events": [
                {
                    "event_id": 11,
                    "assumption_id": 70,
                    "assumption_text": "=SUM(A1:A2)",
                    "category": "Demand",
                    "sensitivity": "HIGH",
                    "method": "USER_INTERVIEW",
                    "method_label": "User interview",
                    "result": "PASS",
                    "observed_metric": 0.42,
                    "notes": "35 responses",
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "derived_confidence": "DESIGN_INTENT",
                    "status_after": "DE_RISKED",
                },
                {
                    "event_id": 12,
                    "assumption_id": 71,
                    "assumption_text": "Customers will return",
                    "category": "Retention",
                    "sensitivity": "MEDIUM",
                    "method": "LANDING_PAGE_TEST",
                    "method_label": "Landing page test",
                    "result": "INCONCLUSIVE",
                    "observed_metric": None,
                    "notes": None,
                    "created_at": "2026-08-05T00:00:00+00:00",
                    "derived_confidence": None,
                    "status_after": "INCONCLUSIVE",
                },
            ],
            "progress": [
                {
                    "event_id": 11,
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "evidence_rows": 1,
                    "assumptions_with_evidence": 1,
                    "de_risked_count": 1,
                    "challenged_count": 0,
                    "inconclusive_count": 0,
                    "pending_count": 1,
                    "validation_score": 0.5,
                    "evidence_coverage_pct": 0.5,
                },
            ],
            "assumptions": [
                {
                    "assumption_id": 70,
                    "assumption_text": "=SUM(A1:A2)",
                    "category": "Demand",
                    "sensitivity": "HIGH",
                    "evidence_count": 1,
                    "status": "DE_RISKED",
                    "first_evidence_event_id": 11,
                    "latest_evidence_event_id": 11,
                    "first_de_risked_event_id": 11,
                    "first_challenged_event_id": None,
                },
            ],
            "milestones": {
                "first_evidence_event_id": 11,
                "last_evidence_event_id": 12,
                "first_de_risked_event_id": 11,
                "first_challenged_event_id": None,
                "first_inconclusive_event_id": 12,
            },
            "meta": {"model": "validation_timeline_v1"},
        }
    )


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    format: str = "csv",
    payload: AssumptionValidationTimelineOut | None = None,
) -> Any:
    from app.api.v1 import assumption_evidence as ev_mod

    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        ev_mod,
        "get_assumption_validation_timeline",
        lambda **kwargs: fake_payload,
    )
    return ev_mod.export_assumption_validation_timeline(
        project_id=7,
        format=format,
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
    path = "/projects/{project_id}/assumption-validation-timeline/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_returns_csv_with_all_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="validation-timeline-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Timeline Summary" in text
    assert "section,Milestones" in text
    assert "section,Events" in text
    assert "section,Progress" in text
    assert "section,Assumptions" in text
    assert "total_evidence_rows,2" in text
    assert "first_de_risked_event_id,11" in text
    # Formula-leading assumption text is neutralised in every section.
    assert "70,'=SUM(A1:A2),Demand,HIGH,1,DE_RISKED" in text
    assert (
        "11,2026-08-01T00:00:00+00:00,70,'=SUM(A1:A2),Demand,HIGH,"
        "User interview,PASS,0.42,DE_RISKED,35 responses" in text
    )
    assert (
        "11,2026-08-01T00:00:00+00:00,1,1,1,0,0,1,0.5,0.5" in text
    )
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_route_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="validation-timeline-7.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["format_version"] == "1"
    timeline = parsed["validation_timeline"]
    assert timeline["project_id"] == 7
    assert timeline["events"][0]["event_id"] == 11
    assert timeline["milestones"]["first_inconclusive_event_id"] == 12


def test_export_rejects_unknown_format_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list[dict[str, Any]] = []

    def forbidden_timeline(**kwargs: Any) -> AssumptionValidationTimelineOut:
        calls.append(kwargs)
        raise AssertionError("timeline should not build for an invalid format")

    monkeypatch.setattr(
        ev_mod, "get_assumption_validation_timeline", forbidden_timeline
    )
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail
    assert calls == []


def test_export_route_returns_markdown_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="validation-timeline-7.md"'
        in response.headers["Content-Disposition"]
    )
    body = _body(response).decode("utf-8")
    assert "# Validation Timeline" in body
    assert "## Summary" in body
    assert "| Total assumptions | 2 |" in body
    assert "## Milestones" in body
    assert "| First de-risked (PASS) | 11 |" in body
    # Only milestones that have occurred get a row.
    assert "First challenged (FAIL)" not in body
    assert "## Events" in body
    assert "| User interview | PASS | DE_RISKED | 35 responses |" in body
    assert int(response.headers["Content-Length"]) == len(body.encode("utf-8"))


def test_markdown_handles_empty_timeline() -> None:
    """A project without experiments still renders a complete brief."""
    from app.simulation.validation_timeline_export import (
        validation_timeline_to_markdown,
    )

    body = validation_timeline_to_markdown(
        {
            "project_id": 9,
            "total_assumptions": 0,
            "total_evidence_rows": 0,
            "events": [],
            "milestones": {},
        }
    )
    assert "# Validation Timeline" in body
    assert "_No milestones yet" in body
    assert "## Events" not in body


def test_markdown_escapes_pipes_in_events() -> None:
    """Pipes in assumption text or notes cannot break the events table."""
    from app.simulation.validation_timeline_export import (
        validation_timeline_to_markdown,
    )

    body = validation_timeline_to_markdown(
        {
            "project_id": 7,
            "events": [
                {
                    "event_id": 13,
                    "assumption_id": 72,
                    "assumption_text": "Will users pay | more later?",
                    "method_label": "Survey",
                    "result": "PASS",
                    "status_after": "DE_RISKED",
                    "notes": "n=40 | strong signal",
                },
            ],
        }
    )
    event_row = next(
        line for line in body.splitlines() if "strong signal" in line
    )
    assert "\\|" in event_row
    # Ignoring escaped pipes, the 6-column table keeps exactly 7 separators.
    assert event_row.replace("\\|", "").count("|") == 7
