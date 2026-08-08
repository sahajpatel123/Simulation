"""
Route-level tests for ``GET /api/v1/projects/{id}/outcome-benchmark``.

Covers ownership lookup, current-outcome selection with predicted-conversion
extraction, category fallback to the latest completed simulation, peer-cohort
scoping, and the no-outcome degradation path.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.outcome_benchmark import OutcomeBenchmarkOut  # noqa: E402

_MISSING = object()


def _current_row(
    *,
    category: str | None = "saas",
    actual: float = 0.06,
    results: dict | None = None,
) -> dict:
    return {
        "id": 1,
        "simulation_id": 7,
        "project_id": 10,
        "days_since_launch": 30,
        "actual_conversion_rate": actual,
        "launched": True,
        "data_confidence": "ESTIMATED",
        "created_at": "2026-08-01T00:00:00+00:00",
        "results_json": results
        if results is not None
        else {"population_weighted_conversion": 0.04},
        "product_type_detected": category,
    }


def _peer_rows() -> list[dict]:
    return [
        {"actual_conversion_rate": 0.01, "product_changed_since_sim": False},
        {"actual_conversion_rate": 0.02, "product_changed_since_sim": False},
        {"actual_conversion_rate": 0.03, "product_changed_since_sim": False},
        {"actual_conversion_rate": 0.04, "product_changed_since_sim": False},
        {"actual_conversion_rate": 0.05, "product_changed_since_sim": False},
    ]


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def first(self) -> dict | None:
        return self.rows[0] if self.rows else None

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
    def __init__(self, project: _FakeProject | None) -> None:
        self.project = project

    def filter(self, *args, **kwargs) -> _FakeProjectQuery:
        return self

    def first(self) -> _FakeProject | None:
        return self.project


class _FakeSession:
    def __init__(
        self,
        *,
        current: dict | None = None,
        fallback_category: str | None = None,
        peers: list[dict] | None = None,
        project: _FakeProject | None | object = _MISSING,
        sql_calls: list[str] | None = None,
    ) -> None:
        self.current = current
        self.fallback_category = fallback_category
        self.peers = peers if peers is not None else _peer_rows()
        self.project = (
            _FakeProject() if project is _MISSING else project
        )
        self.sql_calls = sql_calls

    def query(self, *args, **kwargs) -> _FakeProjectQuery:
        return _FakeProjectQuery(self.project)

    def execute(self, statement, params=None) -> _FakeResult:
        sql = getattr(statement, "text", str(statement))
        if self.sql_calls is not None:
            self.sql_calls.append(sql)
        if "FROM founder_outcomes fo" in sql and "fo.project_id = :pid" in sql:
            return _FakeResult([self.current] if self.current is not None else [])
        if "FROM simulations" in sql and "project_id = :pid" in sql:
            if self.fallback_category:
                return _FakeResult(
                    [{"product_type_detected": self.fallback_category}]
                )
            return _FakeResult([])
        return _FakeResult(self.peers)


def _call_route(
    *,
    project_id: int = 10,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> OutcomeBenchmarkOut:
    from app.api.v1 import outcomes as out_mod

    db = session if session is not None else _FakeSession()
    return out_mod.get_outcome_benchmark(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": user_id})(),
    )


def test_outcome_benchmark_returns_ranked_payload() -> None:
    result = _call_route(
        session=_FakeSession(current=_current_row()),
    )

    assert isinstance(result, OutcomeBenchmarkOut)
    assert result.has_data is True
    assert result.category == "saas"
    assert result.current is not None
    assert result.current.actual_conversion_rate == pytest.approx(0.06)
    assert result.current.predicted_conversion_rate == pytest.approx(0.04)
    assert result.distribution.peer_count == 5
    assert result.percentile_rank == 100.0
    assert result.verdict == "TOP_QUARTILE"
    assert result.meta["peers_usable"] == 5


def test_outcome_benchmark_no_outcome_returns_no_data() -> None:
    result = _call_route(session=_FakeSession(current=None))

    assert result.has_data is False
    assert result.current is None
    assert result.distribution.peer_count == 0
    assert "Record a founder outcome" in result.insights[0]


def test_outcome_benchmark_requires_owner() -> None:
    session = _FakeSession(project=None)
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 404
    assert "Project not found" in exc.value.detail


def test_outcome_benchmark_falls_back_to_latest_simulation_category() -> None:
    result = _call_route(
        session=_FakeSession(
            current=_current_row(category=None),
            fallback_category="hardware",
        )
    )

    assert result.category == "hardware"
    assert result.has_data is True
    assert result.distribution.peer_count == 5


def test_outcome_benchmark_scopes_peer_query_safely() -> None:
    calls: list[str] = []
    _call_route(
        session=_FakeSession(current=_current_row(), sql_calls=calls)
    )

    sql = "\n".join(calls)
    assert "LEFT JOIN simulations s ON s.id = fo.simulation_id" in sql
    assert "p.id <> :pid" in sql
    assert "COALESCE(fo.launched, FALSE) = TRUE" in sql
    assert "s.results_json->>'product_type_detected' = :pt" in sql
    assert "LIMIT :limit" in sql


def test_outcome_benchmark_uses_linked_simulation_category_when_present() -> None:
    calls: list[str] = []
    result = _call_route(
        session=_FakeSession(current=_current_row(), sql_calls=calls)
    )

    assert result.category == "saas"
    # The linked simulation already carries the category, so no fallback
    # query should have run.
    assert not any(
        "results_json->>'product_type_detected' IS NOT NULL" in call
        for call in calls
    )
