"""Route and serialization tests for validation-dashboard exports.

Covers CSV, JSON, and Markdown rendering of the combined dashboard payload,
format validation, and that the ``target_de_risked_pct`` query parameter
flows through to the dashboard builder.
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

from app.schemas.validation_dashboard import ValidationDashboardOut


def _payload() -> ValidationDashboardOut:
    return ValidationDashboardOut.model_validate(
        {
            "project_id": 7,
            "evidence_digest": {
                "project_id": 7,
                "total_assumptions": 2,
                "total_evidence_rows": 3,
                "assumptions_with_evidence": 1,
                "evidence_coverage_pct": 0.5,
                "de_risked_count": 1,
                "challenged_count": 0,
                "inconclusive_count": 0,
                "pending_count": 1,
                "validation_score": 0.5,
                "result_counts": {"PASS": 2, "INCONCLUSIVE": 1},
                "method_counts": {"USER_INTERVIEW": 3},
                "next_action": "Run an interview with the pending segment.",
                "assumptions": [
                    {
                        "assumption_id": 70,
                        "assumption_text": "=SUM(A1:A2)",
                        "category": "Demand",
                        "sensitivity": "HIGH",
                        "evidence_count": 2,
                        "latest_result": "PASS",
                        "derived_confidence": "DESIGN_INTENT",
                        "status": "DE_RISKED",
                    },
                    {
                        "assumption_id": 71,
                        "assumption_text": "Customers will return",
                        "category": "Retention",
                        "sensitivity": "MEDIUM",
                        "evidence_count": 0,
                        "latest_result": None,
                        "derived_confidence": None,
                        "status": "PENDING",
                    },
                ],
            },
            "timeline_milestones": {
                "first_evidence_event_id": 11,
                "last_evidence_event_id": 13,
                "first_de_risked_event_id": 12,
                "first_challenged_event_id": None,
                "first_inconclusive_event_id": 13,
            },
            "evidence_freshness": {
                "total_assumptions": 2,
                "tested_assumptions": 1,
                "fresh_count": 0,
                "aging_count": 0,
                "stale_count": 1,
                "never_tested_count": 1,
                "unknown_count": 0,
                "actionable_count": 2,
                "fresh_share_of_tested_pct": 0.0,
                "stale_share_pct": 0.5,
                "oldest_days_since_evidence": 92.0,
            },
            "retest_queue_top": [
                {
                    "assumption_id": 71,
                    "assumption_text": "Customers will return",
                    "category": "Retention",
                    "sensitivity": "MEDIUM",
                    "evidence_count": 0,
                    "freshness": "NEVER_TESTED",
                },
            ],
            "momentum": {
                "project_id": 7,
                "counts": {
                    "total_assumptions": 2,
                    "total_evidence_rows": 3,
                    "assumptions_with_evidence": 1,
                    "de_risked_count": 1,
                    "challenged_count": 0,
                    "inconclusive_count": 0,
                    "pending_count": 1,
                    "evidence_coverage_pct": 0.5,
                    "validation_score": 0.5,
                },
                "velocity": {
                    "trend": "STEADY",
                    "overall_events_per_week": 2.1,
                    "recent_events_per_week": 2.4,
                    "recent_window_days": 28,
                    "events_last_28_days": 3,
                    "first_evidence_at": "2026-08-01T00:00:00+00:00",
                    "latest_evidence_at": "2026-08-12T00:00:00+00:00",
                    "evidence_span_days": 11.0,
                    "coverage_velocity_per_week": 0.7,
                    "de_risk_velocity_per_week": 0.5,
                },
                "forecast": {
                    "target_de_risked_pct": 1.0,
                    "target_de_risked_count": 2,
                    "remaining_for_coverage": 1,
                    "remaining_for_target": 1,
                    "weeks_to_full_coverage": 1.43,
                    "projected_full_coverage_at": "2026-08-22T00:00:00+00:00",
                    "weeks_to_de_risked_target": 2.0,
                    "projected_de_risked_at": "2026-08-26T00:00:00+00:00",
                    "confident": True,
                    "caveats": [],
                },
                "insights": ["Keep the current cadence."],
                "meta": {"model": "validation_momentum_v1"},
            },
            "meta": {
                "generated_at": "2026-08-18T00:00:00+00:00",
                "model": "validation_dashboard_v1",
            },
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
    target_de_risked_pct: float = 1.0,
    fresh_days: int = 14,
    aging_days: int = 45,
    payload: ValidationDashboardOut | None = None,
) -> Any:
    from app.api.v1 import assumption_evidence as ev_mod

    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        ev_mod,
        "get_validation_dashboard",
        lambda **kwargs: fake_payload,
    )
    return ev_mod.export_validation_dashboard(
        project_id=7,
        format=format,
        target_de_risked_pct=target_de_risked_pct,
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
    path = "/projects/{project_id}/validation-dashboard/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_returns_csv_and_preserves_dashboard_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="validation-dashboard-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Validation Dashboard Summary" in text
    assert "section,Validation Milestones" in text
    assert "section,Evidence Freshness" in text
    assert "section,Top Re-tests" in text
    assert "section,Assumptions" in text
    assert "never_tested_count,1" in text
    assert "71,Customers will return,,NEVER_TESTED" in text
    assert "momentum_trend,STEADY" in text
    assert "first_de_risked_event_id,12" in text
    assert "70,'=SUM(A1:A2),Demand,HIGH,2,PASS" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_route_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="validation-dashboard-7.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["format_version"] == "1"
    dashboard = parsed["validation_dashboard"]
    assert dashboard["project_id"] == 7
    assert dashboard["momentum"]["forecast"]["remaining_for_target"] == 1
    assert dashboard["evidence_digest"]["assumptions"][0]["assumption_id"] == 70


def test_export_forwards_target_to_dashboard_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    seen: dict[str, Any] = {}

    def fake_dashboard(**kwargs: Any) -> ValidationDashboardOut:
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr(ev_mod, "get_validation_dashboard", fake_dashboard)
    ev_mod.export_validation_dashboard(
        project_id=7,
        format="csv",
        target_de_risked_pct=0.75,
        fresh_days=14,
        aging_days=45,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert seen["target_de_risked_pct"] == 0.75
    assert seen["project_id"] == 7


def test_export_forwards_freshness_windows_to_dashboard_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    seen: dict[str, Any] = {}

    def fake_dashboard(**kwargs: Any) -> ValidationDashboardOut:
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr(ev_mod, "get_validation_dashboard", fake_dashboard)
    ev_mod.export_validation_dashboard(
        project_id=7,
        format="csv",
        fresh_days=21,
        aging_days=90,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert seen["fresh_days"] == 21
    assert seen["aging_days"] == 90


def test_export_rejects_unknown_format_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list[dict[str, Any]] = []

    def forbidden_dashboard(**kwargs: Any) -> ValidationDashboardOut:
        calls.append(kwargs)
        raise AssertionError("dashboard should not build for an invalid format")

    monkeypatch.setattr(ev_mod, "get_validation_dashboard", forbidden_dashboard)
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
        'filename="validation-dashboard-7.md"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response).decode("utf-8")
    assert "# Validation Dashboard" in body
    assert "## Summary" in body
    assert "## Validation Milestones" in body
    assert "## Evidence Freshness" in body
    assert "### Top Re-tests" in body
    assert "| Stale share | 50.0% |" in body
    assert "| Customers will return | — | NEVER_TESTED |" in body
    assert "## Assumptions" in body
    assert "first_de_risked_event_id" not in body
    assert "First de-risked (PASS)" in body
    assert "Total assumptions" in body
    assert "De-risked" in body
    assert int(response.headers["Content-Length"]) == len(body.encode("utf-8"))


def test_markdown_summary_uses_human_labels_and_percentages() -> None:
    """Fraction metrics read as percentages and every key has a label."""
    from app.simulation.validation_dashboard_export import (
        validation_dashboard_to_markdown,
    )

    body = validation_dashboard_to_markdown(_payload())

    assert "| Evidence coverage | 50.0% |" in body
    assert "| Validation score | 50.0% |" in body
    assert "| De-risk target share | 100.0% |" in body
    assert "| Project ID | 7 |" in body
    # No snake_case keys leak into the founder-facing summary table.
    for raw_key in (
        "project_id",
        "target_de_risked_pct",
        "target_de_risked_count",
    ):
        assert f"| {raw_key} |" not in body


def test_markdown_escapes_pipe_in_milestones_and_counts() -> None:
    """A pipe inside a milestone id or count cannot break table columns."""
    from app.simulation.validation_dashboard_export import (
        validation_dashboard_to_markdown,
    )

    body = validation_dashboard_to_markdown(
        {
            "project_id": 7,
            "evidence_digest": {
                "assumptions": [
                    {
                        "assumption_id": 70,
                        "assumption_text": "Will users convert?",
                        "category": "Demand",
                        "sensitivity": "HIGH",
                        "evidence_count": "3|4",
                        "latest_result": "PASS",
                    }
                ]
            },
            "timeline_milestones": {
                "first_evidence_event_id": "11|bogus",
            },
        }
    )

    milestone_row = next(
        line for line in body.splitlines() if "First evidence" in line
    )
    assert milestone_row == "| First evidence | 11\\|bogus |"
    assumption_row = next(
        line for line in body.splitlines() if "Will users convert?" in line
    )
    assert "3\\|4" in assumption_row
    # Ignoring escaped pipes, the 8-column table keeps exactly 9 separators.
    assert assumption_row.replace("\\|", "").count("|") == 9
