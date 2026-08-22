"""Route and serialization tests for portfolio validation-momentum exports.

Covers CSV, JSON, and Markdown rendering of the cross-project momentum
payload, format validation, and that ``target_de_risked_pct`` flows
through to the portfolio getter.
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

from app.schemas.portfolio_validation_momentum import (
    PortfolioValidationMomentumOut,
)


def _payload() -> PortfolioValidationMomentumOut:
    return PortfolioValidationMomentumOut.model_validate(
        {
            "user_id": 42,
            "generated_at": "2026-08-23T00:00:00+00:00",
            "summary": {
                "project_count": 2,
                "projects_with_evidence": 1,
                "projects_without_evidence": 1,
                "projects_needing_attention": 1,
                "projects_complete": 0,
                "total_assumptions": 4,
                "total_evidence_rows": 3,
                "assumptions_with_evidence": 2,
                "de_risked_count": 1,
                "challenged_count": 1,
                "pending_count": 2,
                "evidence_coverage_pct": 0.5,
                "validation_score": 0.25,
                "coverage_velocity_per_week": 0.8,
                "de_risk_velocity_per_week": 0.4,
                "target_de_risked_pct": 1.0,
                "remaining_for_coverage": 2,
                "remaining_for_target": 3,
                "weeks_to_full_coverage": 2.5,
                "weeks_to_de_risked_target": 7.5,
                "portfolio_trend": "STEADY",
                "focus_project_id": 10,
                "focus_project_title": "=SUM(A1) app",
                "focus_reason": "Highest pending share with fresh cadence",
                "insights": [
                    "Two projects can run experiments in parallel.",
                ],
                "caveats": ["Velocities estimated from thin samples."],
            },
            "projects": [
                {
                    "project_id": 10,
                    "project_title": "=SUM(A1) app",
                    "rank": 1,
                    "status": "NEEDS_ATTENTION",
                    "trend": "ACCELERATING",
                    "total_assumptions": 3,
                    "de_risked_count": 1,
                    "challenged_count": 1,
                    "pending_count": 1,
                    "evidence_coverage_pct": 0.6667,
                    "validation_score": 0.3333,
                    "remaining_for_target": 2,
                    "weeks_to_de_risked_target": 5.0,
                    "confident": True,
                    "focus_reason": "Highest pending share",
                },
                {
                    "project_id": 11,
                    "project_title": "Side idea | notes",
                    "rank": 2,
                    "status": "NO_EVIDENCE",
                    "trend": "NO_EVIDENCE",
                    "total_assumptions": 1,
                    "pending_count": 1,
                    "remaining_for_target": 1,
                    "confident": False,
                    "focus_reason": "",
                },
            ],
            "meta": {"model": "portfolio_validation_momentum_v1"},
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
    payload: PortfolioValidationMomentumOut | None = None,
) -> Any:
    from app.api.v1 import users as users_mod

    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        users_mod,
        "get_my_validation_momentum",
        lambda **kwargs: fake_payload,
    )
    return users_mod.export_my_validation_momentum(
        format=format,
        target_de_risked_pct=target_de_risked_pct,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    from app.api.v1 import users as users_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in users_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/users/me/validation-momentum/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_returns_csv_with_all_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="portfolio-validation-momentum-u42.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Portfolio Summary" in text
    assert "section,Portfolio Insights" in text
    assert "section,Portfolio Caveats" in text
    assert "section,Projects" in text
    assert "portfolio_trend,STEADY" in text
    assert "evidence_coverage_pct,0.5" in text
    assert "Two projects can run experiments in parallel." in text
    # Formula-leading project titles are neutralised in the projects table.
    assert "1,10,'=SUM(A1) app,NEEDS_ATTENTION,ACCELERATING" in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_export_route_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="portfolio-validation-momentum-u42.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["user_id"] == 42
    assert parsed["metadata"]["format_version"] == "1"
    momentum = parsed["portfolio_validation_momentum"]
    assert momentum["summary"]["project_count"] == 2
    assert momentum["projects"][0]["rank"] == 1


def test_export_forwards_target_to_portfolio_getter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import users as users_mod

    seen: dict[str, Any] = {}

    def fake_momentum(**kwargs: Any) -> PortfolioValidationMomentumOut:
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr(users_mod, "get_my_validation_momentum", fake_momentum)
    users_mod.export_my_validation_momentum(
        format="csv",
        target_de_risked_pct=0.6,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert seen["target_de_risked_pct"] == 0.6


def test_export_rejects_unknown_format_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import users as users_mod

    calls: list[dict[str, Any]] = []

    def forbidden_momentum(**kwargs: Any) -> PortfolioValidationMomentumOut:
        calls.append(kwargs)
        raise AssertionError(
            "momentum should not build for an invalid format"
        )

    monkeypatch.setattr(users_mod, "get_my_validation_momentum", forbidden_momentum)
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
        'filename="portfolio-validation-momentum-u42.md"'
        in response.headers["Content-Disposition"]
    )
    body = _body(response).decode("utf-8")
    assert "# Portfolio Validation Momentum" in body
    assert "**Next focus: =SUM(A1) app** — Highest pending share" in body
    assert "| Coverage | 50.0% |" in body
    assert "| Validation score | 25.0% |" in body
    assert "| De-risk target share | 100.0% |" in body
    assert "- Two projects can run experiments in parallel." in body
    assert "### Caveats" in body
    assert "| Rank | Project | Status | De-risked | Pending |" in body
    assert "| 2 | Side idea \\| notes | NO_EVIDENCE |" in body
    # No raw snake_case keys leak into the founder-facing summary.
    assert "| evidence_coverage_pct |" not in body


def test_markdown_escapes_pipes_in_project_cells() -> None:
    """Pipes in titles cannot break the projects table."""
    from app.simulation.portfolio_validation_momentum_export import (
        portfolio_validation_momentum_to_markdown,
    )

    body = portfolio_validation_momentum_to_markdown(_payload())
    project_row = next(
        line for line in body.splitlines() if "Side idea" in line
    )
    assert "\\|" in project_row
    # Ignoring escaped pipes, the 7-column table keeps exactly 8 separators.
    assert project_row.replace("\\|", "").count("|") == 8
