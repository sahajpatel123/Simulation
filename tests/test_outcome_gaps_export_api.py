"""Route-level tests for the outcome-gaps digest export endpoints."""

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

from app.schemas.outcome_gaps import (
    ProjectOutcomeGapsOut,
    ProjectOutcomeGapsSummary,
    SimulationOutcomeGapItem,
)
from app.schemas.portfolio_outcome_gaps import (
    PortfolioOutcomeGapItem,
    PortfolioOutcomeGapProject,
    PortfolioOutcomeGapsOut,
    PortfolioOutcomeGapsSummary,
)

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _project_payload() -> ProjectOutcomeGapsOut:
    return ProjectOutcomeGapsOut(
        project_id=7,
        generated_at=_NOW.isoformat(),
        summary=ProjectOutcomeGapsSummary(
            total_completed=10,
            scored=4,
            unscored=6,
            coverage_rate_pct=40.0,
            learning_eligible_unscored=2,
            oldest_unscored_age_days=40,
            narrative=(
                "Only 4 of 10 completed runs have outcome feedback (40.0%)."
            ),
        ),
        items=[
            SimulationOutcomeGapItem(
                simulation_id=7,
                created_at=_NOW - timedelta(days=45),
                age_days=45,
                signal_quality=0.6,
                predicted_conversion_rate=0.042,
                product_type_detected="saas",
                primary_failure_domain="pricing",
                has_results=True,
                learning_eligible=True,
                urgency="HIGH",
                recommendation="Score this run now.",
            )
        ],
        limit=50,
        has_more=False,
    )


def _portfolio_payload() -> PortfolioOutcomeGapsOut:
    return PortfolioOutcomeGapsOut(
        user_id=42,
        generated_at=_NOW.isoformat(),
        summary=PortfolioOutcomeGapsSummary(
            project_count=1,
            projects_with_gaps=1,
            total_completed=10,
            scored=4,
            unscored=6,
            coverage_rate_pct=40.0,
            learning_eligible_unscored=2,
            high_priority_unscored=1,
            oldest_unscored_age_days=40,
            narrative="Portfolio outcome feedback is lagging.",
        ),
        projects=[
            PortfolioOutcomeGapProject(
                project_id=7,
                total_completed=10,
                scored=4,
                unscored=6,
                coverage_rate_pct=40.0,
                learning_eligible_unscored=2,
                high_priority_unscored=1,
                oldest_unscored_age_days=40,
            )
        ],
        items=[
            PortfolioOutcomeGapItem(
                project_id=7,
                simulation_id=7,
                created_at=_NOW - timedelta(days=45),
                age_days=45,
                signal_quality=0.6,
                predicted_conversion_rate=0.042,
                product_type_detected="saas",
                primary_failure_domain="pricing",
                has_results=True,
                learning_eligible=True,
                urgency="HIGH",
                recommendation="Score this run now.",
            )
        ],
        limit=50,
        has_more=False,
        learning_eligible_only=False,
    )


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def _user() -> object:
    return type("U", (), {"id": 42})()


# ── Per-project export route ───────────────────────────────────────────


def _call_project_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_id: int = 7,
    format: str = "csv",
    learning_eligible_only: bool = False,
    payload: ProjectOutcomeGapsOut | None = None,
) -> Any:
    from app.api.v1 import outcomes as out_mod

    fake_payload = payload if payload is not None else _project_payload()
    monkeypatch.setattr(
        out_mod,
        "get_project_outcome_gaps",
        lambda **kwargs: fake_payload,
    )
    return out_mod.export_project_outcome_gaps(
        project_id=project_id,
        format=format,
        learning_eligible_only=learning_eligible_only,
        db=object(),  # type: ignore[arg-type]
        current_user=_user(),
    )


def test_project_export_route_registered() -> None:
    from app.api.v1 import outcomes as out_mod

    expected = "/projects/{project_id}/outcome-gaps/export"
    paths = {route.path for route in out_mod.router.routes}
    assert expected in paths
    for route in out_mod.router.routes:
        if route.path == expected:
            assert "GET" in (route.methods or set())


def test_project_export_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _call_project_route(monkeypatch=monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="outcome-gaps-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Outcome Feedback Gaps Summary" in text
    assert "section,Unscored Simulations" in text
    assert "7,2026-06-28T12:00:00+00:00,45,0.6,0.042" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_project_export_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _call_project_route(monkeypatch=monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="outcome-gaps-7.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    gaps = parsed["outcome_gaps"]
    assert gaps["project_id"] == 7
    assert gaps["summary"]["unscored"] == 6
    assert len(gaps["items"]) == 1


def test_project_export_returns_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_project_route(monkeypatch=monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="outcome-gaps-7.md"'
        in response.headers["Content-Disposition"]
    )
    text = _body(response).decode("utf-8")
    assert text.startswith("# Outcome Feedback Gaps")
    assert "## Summary" in text
    assert "## Unscored Simulations" in text


def test_project_export_forwards_full_limit_and_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    calls: list[dict[str, Any]] = []

    def _capture(**kwargs: Any) -> ProjectOutcomeGapsOut:
        calls.append(kwargs)
        return _project_payload()

    monkeypatch.setattr(out_mod, "get_project_outcome_gaps", _capture)
    out_mod.export_project_outcome_gaps(
        project_id=7,
        format="csv",
        learning_eligible_only=True,
        db=object(),  # type: ignore[arg-type]
        current_user=_user(),
    )

    assert len(calls) == 1
    assert calls[0]["project_id"] == 7
    assert calls[0]["limit"] == 100_000
    assert calls[0]["learning_eligible_only"] is True


def test_project_export_accepts_uppercase_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_project_route(monkeypatch=monkeypatch, format="JSON")
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["outcome_gaps"]["project_id"] == 7


def test_project_export_rejects_unknown_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_project_route(monkeypatch=monkeypatch, format="pdf")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_project_export_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    calls: list[dict[str, Any]] = []

    def _forbidden_get(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(out_mod, "get_project_outcome_gaps", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        out_mod.export_project_outcome_gaps(
            project_id=7,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=_user(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []


def test_project_export_forwards_missing_project_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import outcomes as out_mod

    def _not_found(**kwargs: Any) -> Any:
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(out_mod, "get_project_outcome_gaps", _not_found)

    with pytest.raises(HTTPException) as exc_info:
        out_mod.export_project_outcome_gaps(
            project_id=999,
            format="csv",
            db=object(),  # type: ignore[arg-type]
            current_user=_user(),
        )

    assert exc_info.value.status_code == 404


# ── Portfolio export route ─────────────────────────────────────────────


def _call_portfolio_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    format: str = "csv",
    learning_eligible_only: bool = False,
    payload: PortfolioOutcomeGapsOut | None = None,
) -> Any:
    from app.api.v1 import users as users_mod

    fake_payload = payload if payload is not None else _portfolio_payload()
    monkeypatch.setattr(
        users_mod,
        "get_my_outcome_gaps",
        lambda **kwargs: fake_payload,
    )
    return users_mod.export_my_outcome_gaps(
        format=format,
        learning_eligible_only=learning_eligible_only,
        db=object(),  # type: ignore[arg-type]
        current_user=_user(),
    )


def test_portfolio_export_route_registered() -> None:
    from app.api.v1 import users as users_mod

    expected = "/users/me/outcome-gaps/export"
    paths = {route.path for route in users_mod.router.routes}
    assert expected in paths
    for route in users_mod.router.routes:
        if route.path == expected:
            assert "GET" in (route.methods or set())


def test_portfolio_export_returns_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_portfolio_route(monkeypatch=monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="outcome-gaps-portfolio-42.csv"'
        in response.headers["Content-Disposition"]
    )
    text = _body(response).decode("utf-8")
    assert "project_count,1" in text
    assert "simulation_id,project_id,created_at" in text
    assert "7,7,2026-06-28T12:00:00+00:00,45,0.6,0.042" in text


def test_portfolio_export_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_portfolio_route(monkeypatch=monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="outcome-gaps-portfolio-42.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["user_id"] == 42
    assert parsed["outcome_gaps"]["user_id"] == 42
    assert parsed["outcome_gaps"]["items"][0]["project_id"] == 7


def test_portfolio_export_returns_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_portfolio_route(monkeypatch=monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="outcome-gaps-portfolio-42.md"'
        in response.headers["Content-Disposition"]
    )
    text = _body(response).decode("utf-8")
    assert "| Simulation | Project | Created |" in text
    assert "User 42" in text


def test_portfolio_export_forwards_full_limit_and_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import users as users_mod

    calls: list[dict[str, Any]] = []

    def _capture(**kwargs: Any) -> PortfolioOutcomeGapsOut:
        calls.append(kwargs)
        return _portfolio_payload()

    monkeypatch.setattr(users_mod, "get_my_outcome_gaps", _capture)
    users_mod.export_my_outcome_gaps(
        format="csv",
        learning_eligible_only=True,
        db=object(),  # type: ignore[arg-type]
        current_user=_user(),
    )

    assert len(calls) == 1
    assert calls[0]["limit"] == 100_000
    assert calls[0]["learning_eligible_only"] is True


def test_portfolio_export_rejects_unknown_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_portfolio_route(monkeypatch=monkeypatch, format="pdf")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_portfolio_export_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import users as users_mod

    calls: list[dict[str, Any]] = []

    def _forbidden_get(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(users_mod, "get_my_outcome_gaps", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        users_mod.export_my_outcome_gaps(
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=_user(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
