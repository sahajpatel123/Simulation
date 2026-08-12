"""Tests for the portfolio-level outcome-feedback gaps digest.

Covers the pure digest builder (rollup math, narratives, item composition)
and the ``GET /users/me/outcome-gaps`` route (SQL scoping, filtering,
registration).
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.portfolio_outcome_gaps import PortfolioOutcomeGapsOut
from app.simulation.outcome_gaps import URGENCY_HIGH, URGENCY_LOW
from app.simulation.portfolio_outcome_gaps import (
    build_portfolio_outcome_gaps_digest,
)

pytest.importorskip("scipy", reason="Route registration requires scipy")

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _project_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "project_id": 7,
        "total_completed": 10,
        "scored": 4,
        "unscored": 6,
        "learning_eligible_unscored": 2,
        "high_priority_unscored": 1,
        "oldest_unscored_created_at": _NOW - timedelta(days=40),
    }
    row.update(overrides)
    return row


def _item_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "project_id": 7,
        "simulation_id": 7,
        "created_at": _NOW - timedelta(days=45),
        "signal_quality": 0.6,
        "results_json": {
            "population_weighted_conversion": 0.042,
            "product_type_detected": "saas",
            "primary_failure_domain": "pricing",
        },
        "has_results": True,
    }
    row.update(overrides)
    return row


# ── Pure builder tests ──────────────────────────────────────────────


def test_empty_portfolio_digest() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[],
        rows=[],
        limit=50,
        now=_NOW,
    )

    assert payload["user_id"] == 42
    assert payload["items"] == []
    assert payload["has_more"] is False
    summary = payload["summary"]
    assert summary["project_count"] == 0
    assert summary["total_completed"] == 0
    assert summary["coverage_rate_pct"] == 0.0
    assert summary["oldest_unscored_age_days"] is None
    assert "No completed simulations across your portfolio yet" in (
        summary["narrative"]
    )


def test_all_scored_portfolio_digest() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            _project_row(
                total_completed=3,
                scored=3,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                oldest_unscored_created_at=None,
            )
        ],
        rows=[],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["coverage_rate_pct"] == 100.0
    assert summary["projects_with_gaps"] == 0
    assert "All completed simulations across your portfolio" in (
        summary["narrative"]
    )


def test_partial_coverage_summary_math_and_narrative() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            _project_row(),
            _project_row(
                project_id=9,
                total_completed=5,
                scored=3,
                unscored=2,
                learning_eligible_unscored=2,
                high_priority_unscored=0,
                oldest_unscored_created_at=_NOW - timedelta(days=5),
            ),
        ],
        rows=[],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["project_count"] == 2
    assert summary["projects_with_gaps"] == 2
    assert summary["total_completed"] == 15
    assert summary["scored"] == 7
    assert summary["unscored"] == 8
    assert summary["coverage_rate_pct"] == pytest.approx(46.67)
    assert summary["learning_eligible_unscored"] == 4
    assert summary["high_priority_unscored"] == 1
    assert summary["oldest_unscored_age_days"] == 40
    narrative = summary["narrative"]
    assert "Across 2 project(s)" in narrative
    assert "7 of 15" in narrative
    assert "46.7%" in narrative
    assert "8 unscored run(s) remain" in narrative
    assert "4 of which would feed calibration" in narrative
    assert "oldest unscored run is 40 days old" in narrative
    assert "1 of those are 30+ days old" in narrative


def test_per_project_rollup_math() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            _project_row(),
            _project_row(
                project_id=9,
                total_completed=5,
                scored=3,
                unscored=2,
                learning_eligible_unscored=2,
                high_priority_unscored=0,
                oldest_unscored_created_at=_NOW - timedelta(days=5),
            ),
        ],
        rows=[],
        now=_NOW,
    )

    assert [project["project_id"] for project in payload["projects"]] == [7, 9]
    first, second = payload["projects"]
    assert first["total_completed"] == 10
    assert first["scored"] == 4
    assert first["unscored"] == 6
    assert first["coverage_rate_pct"] == 40.0
    assert first["learning_eligible_unscored"] == 2
    assert first["high_priority_unscored"] == 1
    assert first["oldest_unscored_age_days"] == 40
    assert second["coverage_rate_pct"] == 60.0
    assert second["high_priority_unscored"] == 0
    assert second["oldest_unscored_age_days"] == 5


def test_learning_eligible_only_narrative() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            _project_row(
                unscored=2,
                learning_eligible_unscored=2,
                high_priority_unscored=1,
                oldest_unscored_created_at=_NOW - timedelta(days=40),
            )
        ],
        rows=[],
        learning_eligible_only=True,
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["unscored"] == 2
    assert summary["learning_eligible_unscored"] == 2
    assert summary["narrative"].startswith(
        "Showing learning-eligible unscored runs only."
    )
    assert "2 unscored learning-eligible run(s) below" in summary["narrative"]
    assert "would feed calibration" not in summary["narrative"]


def test_learning_eligible_only_with_zero_eligible_gaps_narrative() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            _project_row(
                total_completed=5,
                scored=3,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                oldest_unscored_created_at=None,
            )
        ],
        rows=[],
        learning_eligible_only=True,
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["coverage_rate_pct"] == 60.0
    assert "All completed simulations across your portfolio" not in (
        summary["narrative"]
    )
    assert "No learning-eligible unscored runs remain" in summary["narrative"]


def test_items_include_project_id_and_urgency() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[_project_row()],
        rows=[
            _item_row(
                project_id=9,
                simulation_id=9,
                created_at=_NOW - timedelta(days=2),
                signal_quality=0.1,
            ),
            _item_row(),
        ],
        now=_NOW,
    )

    assert [item["simulation_id"] for item in payload["items"]] == [7, 9]
    assert payload["items"][0]["project_id"] == 7
    assert payload["items"][0]["urgency"] == URGENCY_HIGH
    assert payload["items"][0]["learning_eligible"] is True
    assert payload["items"][1]["project_id"] == 9
    assert payload["items"][1]["urgency"] == URGENCY_LOW


def test_malformed_project_rows_are_tolerated() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[
            None,
            {"project_id": "bad"},
            {
                "project_id": 7,
                "total_completed": "oops",
                "scored": "oops",
                "unscored": 3,
                "learning_eligible_unscored": "oops",
                "high_priority_unscored": 1,
                "oldest_unscored_created_at": "not-a-date",
            },
        ],
        rows=[None, _item_row(project_id=3, simulation_id=3)],
        now=_NOW,
    )

    assert payload["summary"]["project_count"] == 1
    assert payload["summary"]["total_completed"] == 0
    assert payload["summary"]["unscored"] == 3
    assert payload["summary"]["learning_eligible_unscored"] == 0
    assert payload["summary"]["oldest_unscored_age_days"] is None
    assert payload["projects"][0]["oldest_unscored_age_days"] is None
    assert payload["items"][0]["project_id"] == 3


def test_has_more_flag_when_page_is_truncated() -> None:
    payload = build_portfolio_outcome_gaps_digest(
        user_id=42,
        project_rows=[_project_row(unscored=5)],
        rows=[_item_row(simulation_id=1), _item_row(simulation_id=2)],
        limit=2,
        now=_NOW,
    )

    assert payload["limit"] == 2
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True


# ── Route tests ─────────────────────────────────────────────────────


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self.rows)


class _FakeSession:
    def __init__(
        self,
        *,
        responses: list[_FakeResult] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def execute(self, statement, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append({"sql": str(statement), "params": params})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResult([])


def _responses(
    *,
    full: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[_FakeResult]:
    return [
        _FakeResult(
            full
            if full is not None
            else [
                {"project_id": 7, "total_completed": 3, "scored": 1},
                {"project_id": 9, "total_completed": 2, "scored": 2},
            ]
        ),
        _FakeResult(
            gaps
            if gaps is not None
            else [
                {
                    "project_id": 7,
                    "unscored": 2,
                    "learning_eligible_unscored": 1,
                    "high_priority_unscored": 1,
                    "oldest_unscored_created_at": _NOW - timedelta(days=40),
                },
                {
                    "project_id": 9,
                    "unscored": 0,
                    "learning_eligible_unscored": 0,
                    "high_priority_unscored": 0,
                    "oldest_unscored_created_at": None,
                },
            ]
        ),
        _FakeResult(
            items
            if items is not None
            else [
                _item_row(),
                _item_row(
                    simulation_id=8,
                    signal_quality=0.1,
                    created_at=_NOW - timedelta(days=3),
                ),
            ]
        ),
    ]


def _call_route(
    *,
    session: _FakeSession | None = None,
    limit: int = 50,
    learning_eligible_only: bool = False,
) -> PortfolioOutcomeGapsOut:
    from app.api.v1 import users as users_mod

    return users_mod.get_my_outcome_gaps(
        limit=limit,
        learning_eligible_only=learning_eligible_only,
        db=session or _FakeSession(responses=_responses()),
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_returns_portfolio_outcome_gaps_payload() -> None:
    result = _call_route()

    assert isinstance(result, PortfolioOutcomeGapsOut)
    assert result.user_id == 42
    assert result.summary.project_count == 2
    assert result.summary.total_completed == 5
    assert result.summary.scored == 3
    assert result.summary.unscored == 2
    assert result.summary.coverage_rate_pct == pytest.approx(60.0)
    assert result.summary.learning_eligible_unscored == 1
    assert result.summary.high_priority_unscored == 1
    assert result.summary.projects_with_gaps == 1
    assert len(result.projects) == 2
    assert len(result.items) == 2
    assert result.items[0].project_id == 7
    assert result.items[0].urgency == URGENCY_HIGH
    assert result.has_more is False


def test_route_sql_is_scoped_and_uses_anti_join() -> None:
    session = _FakeSession(responses=_responses())
    _call_route(session=session)

    sqls = [call["sql"] for call in session.calls]
    assert len(sqls) == 3
    joined = "\n".join(sqls)
    assert "p.user_id = :uid" in joined
    assert "UPPER(s.status) = 'COMPLETED'" in joined
    assert "founder_outcomes fo" in joined
    assert "fo.simulation_id = s.id" in joined
    assert "fo.project_id = s.project_id" in joined
    assert "GROUP BY s.project_id" in joined
    assert "NOT EXISTS" in joined
    assert "ORDER BY s.created_at ASC, s.id ASC" in joined
    assert "LIMIT :limit" in joined
    assert session.calls[0]["params"] == {"uid": 42}
    assert session.calls[2]["params"] == {"uid": 42, "limit": 50}


def test_route_learning_eligible_only_filters_sql_and_params() -> None:
    session = _FakeSession(responses=_responses())
    _call_route(session=session, learning_eligible_only=True)

    sqls = [call["sql"] for call in session.calls]
    assert "COALESCE(s.signal_quality, 0) >= :min_sq" in sqls[1]
    assert "COALESCE(s.signal_quality, 0) >= :min_sq" in sqls[2]
    assert session.calls[1]["params"]["min_sq"] == 0.25
    assert session.calls[1]["params"]["stale_cutoff"] is not None
    assert session.calls[2]["params"]["min_sq"] == 0.25


def test_route_is_registered_on_users_router() -> None:
    from app.api.v1 import users as users_mod

    paths = {route.path for route in users_mod.router.routes}
    assert "/users/me/outcome-gaps" in paths
    for route in users_mod.router.routes:
        if route.path == "/users/me/outcome-gaps":
            assert "GET" in (route.methods or set())
