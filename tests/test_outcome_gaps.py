"""Tests for the per-project outcome-feedback gaps digest.

Covers the pure digest builders (urgency tiers, summary math, narratives)
and the ``GET /projects/{project_id}/outcome-gaps`` route (ownership,
SQL scoping, filtering, registration).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.schemas.outcome_gaps import ProjectOutcomeGapsOut
from app.simulation.outcome_gaps import (
    URGENCY_HIGH,
    URGENCY_LOW,
    URGENCY_MEDIUM,
    build_outcome_gap_item,
    build_outcome_gaps_digest,
)

_MISSING = object()
_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _item_row(**overrides) -> dict:
    row = {
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


def test_empty_project_digest() -> None:
    payload = build_outcome_gaps_digest(
        project_id=10,
        rows=[],
        total_completed=0,
        scored_count=0,
        unscored_total=0,
        learning_eligible_unscored=0,
        oldest_unscored_created_at=None,
        limit=50,
        now=_NOW,
    )

    assert payload["items"] == []
    assert payload["has_more"] is False
    summary = payload["summary"]
    assert summary["total_completed"] == 0
    assert summary["coverage_rate_pct"] == 0.0
    assert summary["oldest_unscored_age_days"] is None
    assert "No completed simulations yet" in summary["narrative"]


def test_all_scored_digest() -> None:
    payload = build_outcome_gaps_digest(
        project_id=10,
        rows=[],
        total_completed=3,
        scored_count=3,
        unscored_total=0,
        learning_eligible_unscored=0,
        oldest_unscored_created_at=None,
        limit=50,
        now=_NOW,
    )

    assert payload["summary"]["coverage_rate_pct"] == 100.0
    assert payload["summary"]["unscored"] == 0
    assert "All completed simulations have recorded outcome feedback" in (
        payload["summary"]["narrative"]
    )


def test_partial_coverage_summary_math_and_narrative() -> None:
    oldest = _NOW - timedelta(days=40)
    payload = build_outcome_gaps_digest(
        project_id=10,
        rows=[],
        total_completed=10,
        scored_count=4,
        unscored_total=6,
        learning_eligible_unscored=2,
        oldest_unscored_created_at=oldest,
        limit=50,
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["scored"] == 4
    assert summary["unscored"] == 6
    assert summary["coverage_rate_pct"] == 40.0
    assert summary["learning_eligible_unscored"] == 2
    assert summary["oldest_unscored_age_days"] == 40
    assert "Only 4 of 10 completed runs have outcome feedback (40.0%)" in (
        summary["narrative"]
    )
    assert "2 of those runs have signal quality ≥ 0.25" in summary["narrative"]


def test_urgency_tiers_and_recommendations() -> None:
    rows = [
        _item_row(  # stale + learning-eligible → HIGH
            simulation_id=1,
            created_at=_NOW - timedelta(days=45),
            signal_quality=0.6,
        ),
        _item_row(  # fresh but learning-eligible → MEDIUM
            simulation_id=2,
            created_at=_NOW - timedelta(days=2),
            signal_quality=0.5,
        ),
        _item_row(  # stale but low signal → MEDIUM
            simulation_id=3,
            created_at=_NOW - timedelta(days=12),
            signal_quality=0.1,
        ),
        _item_row(  # fresh + low signal → LOW
            simulation_id=4,
            created_at=_NOW - timedelta(days=2),
            signal_quality=0.1,
        ),
    ]
    items = [
        build_outcome_gap_item(dict(row), now=_NOW) for row in rows
    ]

    assert [item["urgency"] for item in items] == [
        URGENCY_HIGH,
        URGENCY_MEDIUM,
        URGENCY_MEDIUM,
        URGENCY_LOW,
    ]
    assert "45 days old" in items[0]["recommendation"]
    assert "calibration value" in items[1]["recommendation"]
    assert "12 days old" in items[2]["recommendation"]
    assert "prioritise HIGH and MEDIUM" in items[3]["recommendation"]


def test_item_extracts_results_fields() -> None:
    item = build_outcome_gap_item(_item_row(), now=_NOW)

    assert item["simulation_id"] == 7
    assert item["age_days"] == 45
    assert item["signal_quality"] == 0.6
    assert item["learning_eligible"] is True
    assert item["predicted_conversion_rate"] == 0.042
    assert item["product_type_detected"] == "saas"
    assert item["primary_failure_domain"] == "pricing"
    assert item["has_results"] is True


def test_item_handles_missing_and_malformed_values() -> None:
    item = build_outcome_gap_item(
        _item_row(
            signal_quality=float("nan"),
            results_json=None,
        ),
        now=_NOW,
    )

    assert item["signal_quality"] is None
    assert item["learning_eligible"] is False
    assert item["predicted_conversion_rate"] is None
    assert item["product_type_detected"] is None
    assert item["primary_failure_domain"] is None
    assert item["has_results"] is False


def test_has_more_flag_when_page_is_truncated() -> None:
    payload = build_outcome_gaps_digest(
        project_id=10,
        rows=[_item_row(simulation_id=1), _item_row(simulation_id=2)],
        total_completed=6,
        scored_count=1,
        unscored_total=5,
        learning_eligible_unscored=3,
        oldest_unscored_created_at=_NOW - timedelta(days=10),
        limit=2,
        now=_NOW,
    )

    assert payload["limit"] == 2
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True


def test_learning_eligible_only_narrative() -> None:
    payload = build_outcome_gaps_digest(
        project_id=10,
        rows=[_item_row()],
        total_completed=8,
        scored_count=2,
        unscored_total=3,
        learning_eligible_unscored=3,
        oldest_unscored_created_at=_NOW - timedelta(days=20),
        limit=50,
        learning_eligible_only=True,
        now=_NOW,
    )

    assert payload["summary"]["unscored"] == 3
    assert payload["summary"]["learning_eligible_unscored"] == 3
    assert payload["summary"]["narrative"].startswith(
        "Showing learning-eligible unscored runs only."
    )
    assert "would feed calibration" not in payload["summary"]["narrative"]


# ── Route tests ─────────────────────────────────────────────────────


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def all(self) -> list[dict]:
        return list(self.rows)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self.rows)


class _FakeProject:
    def __init__(self) -> None:
        self.id = 10
        self.user_id = 42


class _FakeProjectQuery:
    def __init__(self, project) -> None:
        self.project = project

    def filter(self, *args, **kwargs) -> _FakeProjectQuery:
        return self

    def first(self):
        return self.project


class _FakeSession:
    def __init__(
        self,
        *,
        responses: list[_FakeResult] | None = None,
        project=_MISSING,
    ) -> None:
        self.responses = list(responses or [])
        self.project = _FakeProject() if project is _MISSING else project
        self.calls: list[dict] = []

    def query(self, *args, **kwargs) -> _FakeProjectQuery:
        return _FakeProjectQuery(self.project)

    def execute(self, statement, params: dict | None = None) -> _FakeResult:
        self.calls.append({"sql": str(statement), "params": params})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResult([])


def _user() -> object:
    return type("U", (), {"id": 42})()


def _responses(
    *,
    total_completed: int = 3,
    scored: int = 1,
    unscored_total: int = 2,
    learning_eligible_unscored: int = 1,
    oldest: datetime | None = None,
    items: list[dict] | None = None,
) -> list[_FakeResult]:
    return [
        _FakeResult([{"total_completed": total_completed}]),
        _FakeResult([{"scored": scored}]),
        _FakeResult([
            {
                "unscored_total": unscored_total,
                "learning_eligible_unscored": learning_eligible_unscored,
                "oldest_unscored_created_at": (
                    oldest or (_NOW - timedelta(days=30))
                ),
            }
        ]),
        _FakeResult(items if items is not None else [_item_row()]),
    ]


def _call_route(
    *,
    db: _FakeSession | None = None,
    project_id: int = 10,
    limit: int = 50,
    learning_eligible_only: bool = False,
) -> ProjectOutcomeGapsOut:
    from app.api.v1 import outcomes as out_mod

    return out_mod.get_project_outcome_gaps(
        project_id=project_id,
        limit=limit,
        learning_eligible_only=learning_eligible_only,
        db=db if db is not None else _FakeSession(),
        current_user=_user(),
    )


def test_route_returns_outcome_gaps_payload() -> None:
    result = _call_route(
        db=_FakeSession(
            responses=_responses(
                items=[
                    _item_row(simulation_id=7, signal_quality=0.6),
                    _item_row(
                        simulation_id=8,
                        signal_quality=0.1,
                        created_at=_NOW - timedelta(days=3),
                    ),
                ]
            )
        )
    )

    assert isinstance(result, ProjectOutcomeGapsOut)
    assert result.project_id == 10
    assert result.summary.total_completed == 3
    assert result.summary.scored == 1
    assert result.summary.unscored == 2
    assert result.summary.coverage_rate_pct == pytest.approx(33.33)
    assert result.summary.learning_eligible_unscored == 1
    assert len(result.items) == 2
    assert result.items[0].simulation_id == 7
    assert result.items[0].learning_eligible is True
    assert result.items[0].urgency == URGENCY_HIGH
    assert result.items[1].urgency == URGENCY_LOW


def test_route_requires_project_owner() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(db=_FakeSession(project=None))
    assert exc.value.status_code == 404
    assert "Project not found" in exc.value.detail


def test_route_query_is_scoped_and_uses_anti_join() -> None:
    session = _FakeSession(responses=_responses())
    _call_route(db=session)

    sqls = [call["sql"] for call in session.calls]
    assert len(sqls) == 4
    joined = "\n".join(sqls)
    assert "s.project_id = :pid" in joined
    assert "UPPER(s.status) = 'COMPLETED'" in joined
    assert "founder_outcomes fo" in joined
    assert "fo.simulation_id = s.id" in joined
    assert "ORDER BY s.created_at ASC, s.id ASC" in joined
    assert "LIMIT :limit" in joined
    assert session.calls[0]["params"] == {"pid": 10}
    assert session.calls[3]["params"] == {"pid": 10, "limit": 50}


def test_route_learning_eligible_only_filters_sql_and_params() -> None:
    session = _FakeSession(
        responses=_responses(
            unscored_total=1,
            learning_eligible_unscored=1,
            items=[_item_row(signal_quality=0.5)],
        )
    )
    result = _call_route(db=session, learning_eligible_only=True)

    assert result.summary.unscored == 1
    assert result.summary.learning_eligible_unscored == 1
    sqls = [call["sql"] for call in session.calls]
    assert "COALESCE(s.signal_quality, 0) >= :min_sq" in sqls[2]
    assert "COALESCE(s.signal_quality, 0) >= :min_sq" in sqls[3]
    assert session.calls[2]["params"]["min_sq"] == 0.25
    assert session.calls[3]["params"]["min_sq"] == 0.25


def test_route_registered_as_get() -> None:
    from app.api.v1 import outcomes as out_mod

    expected = "/projects/{project_id}/outcome-gaps"
    paths = {route.path for route in out_mod.router.routes}
    assert expected in paths
    for route in out_mod.router.routes:
        if route.path == expected:
            assert "GET" in (route.methods or set())
