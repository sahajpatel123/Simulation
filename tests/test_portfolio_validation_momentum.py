"""Tests for the portfolio validation-momentum digest and route."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.portfolio_validation_momentum import (
    PortfolioValidationMomentumOut,
)
from app.simulation.portfolio_validation_momentum import (
    PORTFOLIO_TREND_MIXED,
    PROJECT_STATUS_COMPLETE,
    PROJECT_STATUS_NO_EVIDENCE,
    build_portfolio_validation_momentum,
)

pytest.importorskip("scipy", reason="Route registration imports the API router")

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def _assumption(assumption_id: int, project_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=assumption_id,
        project_id=project_id,
        text=f"Assumption {assumption_id}",
        category="PricingArchitect",
        sensitivity="HIGH",
        impact_score=8.0,
        is_hidden=False,
    )


def _evidence(
    evidence_id: int,
    *,
    project_id: int,
    assumption_id: int,
    day: int = 1,
    result: str = "PASS",
    at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=evidence_id,
        project_id=project_id,
        assumption_id=assumption_id,
        method="WILLINGNESS_TO_PAY_SURVEY",
        result=result,
        observed_metric=0.4,
        notes="logged",
        created_at=at or datetime(2026, 1, day, tzinfo=UTC),
    )


def _project(
    project_id: int,
    title: str,
    assumptions: list[Any],
    evidence: list[Any],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_title": title,
        "assumptions": assumptions,
        "evidence": evidence,
    }


def test_rollup_ranks_no_evidence_and_sums_portfolio_counts() -> None:
    payload = build_portfolio_validation_momentum(
        user_id=42,
        project_rows=[
            _project(
                7,
                "Validated pricing",
                [_assumption(701, 7), _assumption(702, 7)],
                [
                    _evidence(1, project_id=7, assumption_id=701, day=1),
                    _evidence(2, project_id=7, assumption_id=702, day=15),
                ],
            ),
            _project(
                9,
                "Unstarted marketplace",
                [_assumption(901, 9), _assumption(902, 9), _assumption(903, 9)],
                [],
            ),
        ],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["project_count"] == 2
    assert summary["projects_with_evidence"] == 1
    assert summary["projects_without_evidence"] == 1
    assert summary["total_assumptions"] == 5
    assert summary["total_evidence_rows"] == 2
    assert summary["assumptions_with_evidence"] == 2
    assert summary["de_risked_count"] == 2
    assert summary["evidence_coverage_pct"] == 0.4
    assert summary["focus_project_id"] == 9
    assert summary["focus_project_title"] == "Unstarted marketplace"
    assert payload["projects"][0]["status"] == PROJECT_STATUS_NO_EVIDENCE
    assert payload["projects"][0]["rank"] == 1
    assert payload["projects"][0]["focus_reason"].startswith("No evidence")


def test_rollup_marks_disagreeing_active_trends_as_mixed() -> None:
    payload = build_portfolio_validation_momentum(
        user_id=42,
        project_rows=[
            _project(
                1,
                "Accelerating",
                [_assumption(101, 1), _assumption(102, 1)],
                [
                    _evidence(
                        1,
                        project_id=1,
                        assumption_id=101,
                        at=datetime(2025, 11, 1, tzinfo=UTC),
                    ),
                    _evidence(
                        2,
                        project_id=1,
                        assumption_id=102,
                        at=datetime(2026, 1, 10, tzinfo=UTC),
                    ),
                    _evidence(
                        3,
                        project_id=1,
                        assumption_id=101,
                        at=datetime(2026, 1, 20, tzinfo=UTC),
                    ),
                    _evidence(
                        7,
                        project_id=1,
                        assumption_id=102,
                        at=datetime(2026, 1, 25, tzinfo=UTC),
                    ),
                    _evidence(
                        8,
                        project_id=1,
                        assumption_id=101,
                        at=datetime(2026, 1, 30, tzinfo=UTC),
                    ),
                ],
            ),
            _project(
                2,
                "Decelerating",
                [_assumption(201, 2), _assumption(202, 2)],
                [
                    _evidence(
                        4,
                        project_id=2,
                        assumption_id=201,
                        at=datetime(2025, 11, 1, tzinfo=UTC),
                    ),
                    _evidence(
                        5,
                        project_id=2,
                        assumption_id=202,
                        at=datetime(2025, 11, 10, tzinfo=UTC),
                    ),
                    _evidence(
                        6,
                        project_id=2,
                        assumption_id=201,
                        at=datetime(2025, 11, 20, tzinfo=UTC),
                    ),
                    _evidence(
                        9,
                        project_id=2,
                        assumption_id=202,
                        at=datetime(2025, 12, 1, tzinfo=UTC),
                    ),
                    _evidence(
                        10,
                        project_id=2,
                        assumption_id=201,
                        at=datetime(2026, 1, 30, tzinfo=UTC),
                    ),
                ],
            ),
        ],
        now=_NOW,
    )

    assert payload["summary"]["portfolio_trend"] == PORTFOLIO_TREND_MIXED
    assert any("mixed" in insight.lower() for insight in payload["summary"]["insights"])


def test_rollup_handles_empty_portfolio() -> None:
    payload = build_portfolio_validation_momentum(
        user_id=42,
        project_rows=[],
        now=_NOW,
    )

    assert payload["generated_at"] == _NOW
    assert payload["projects"] == []
    assert payload["summary"]["portfolio_trend"] == "NO_EVIDENCE"
    assert payload["summary"]["focus_project_id"] is None
    assert payload["summary"]["focus_reason"] == (
        "Create a project to begin validation."
    )


def test_completed_project_is_not_selected_as_focus() -> None:
    payload = build_portfolio_validation_momentum(
        user_id=42,
        project_rows=[
            _project(
                3,
                "Done",
                [_assumption(301, 3)],
                [_evidence(1, project_id=3, assumption_id=301, day=1)],
            )
        ],
        now=_NOW,
    )

    assert payload["projects"][0]["status"] == PROJECT_STATUS_COMPLETE
    assert payload["summary"]["projects_complete"] == 1
    assert payload["summary"]["focus_project_id"] is None
    assert payload["summary"]["focus_reason"] == (
        "No project needs attention right now."
    )


class _FakeProject:
    def __init__(self, project_id: int, title: str) -> None:
        self.id = project_id
        self.title = title
        self.user_id = 42


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        return self.items


class _FakeSession:
    def __init__(self) -> None:
        self.projects = [_FakeProject(7, "First idea"), _FakeProject(9, "Second idea")]
        self.assumptions = [
            _assumption(701, 7),
            _assumption(702, 7),
            _assumption(901, 9),
        ]
        self.evidence = [
            _evidence(1, project_id=7, assumption_id=701, day=1),
            _evidence(2, project_id=7, assumption_id=702, day=15),
        ]

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery(self.projects)
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        if name == "AssumptionEvidence":
            return _FakeQuery(self.evidence)
        return _FakeQuery([])


def _call_route(session: _FakeSession | None = None) -> PortfolioValidationMomentumOut:
    from app.api.v1 import users as users_mod

    return users_mod.get_my_validation_momentum(
        db=session or _FakeSession(),
        current_user=SimpleNamespace(id=42),
        target_de_risked_pct=1.0,
    )


def test_route_returns_scoped_portfolio_digest() -> None:
    out = _call_route()

    assert isinstance(out, PortfolioValidationMomentumOut)
    assert out.user_id == 42
    assert out.summary.project_count == 2
    assert out.summary.total_evidence_rows == 2
    assert out.summary.focus_project_id == 9
    assert [project.project_id for project in out.projects] == [9, 7]
    assert out.meta["model"] == "portfolio_validation_momentum_v1"


def test_route_is_registered_on_users_router() -> None:
    from app.api.v1 import users as users_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in users_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
    assert "GET" in methods_by_path.get("/users/me/validation-momentum", set())
