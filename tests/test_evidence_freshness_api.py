"""Route-level tests for /projects/{id}/evidence-freshness.

Mirrors the fake-session pattern of the dashboard/momentum API tests: no
real database, just enough session behaviour to exercise ownership checks,
query flow, and payload shaping.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Assumption:
    def __init__(self, assumption_id: int) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = f"Assumption about {assumption_id}"
        self.category = "PricingArchitect"
        self.sensitivity = "HIGH"
        self.impact_score = 9.0
        self.is_hidden = False


class _Evidence:
    def __init__(
        self,
        evidence_id: int,
        *,
        assumption_id: int = 100,
        day: int = 3,
        created_at: datetime | None = None,
    ) -> None:
        self.id = evidence_id
        self.project_id = 10
        self.assumption_id = assumption_id
        self.method = "WILLINGNESS_TO_PAY_SURVEY"
        self.result = "PASS"
        self.observed_metric = 0.42
        self.notes = "35 responses"
        # Default is comfortably in the past so the row reads as stale no
        # matter when the suite runs; pass created_at to pin freshness.
        self.created_at = created_at or datetime(2025, 6, day, tzinfo=UTC)


class _Project:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.user_id = 42


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _Project | None = None,
        project_missing: bool = False,
        assumptions: list | None = None,
        evidence: list | None = None,
    ) -> None:
        self.project = (
            None
            if project_missing
            else (project if project is not None else _Project())
        )
        self.assumptions = (
            assumptions if assumptions is not None else [_Assumption(100)]
        )
        self.evidence = evidence if evidence is not None else []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project is None:
                return _FakeQuery([])
            return _FakeQuery([self.project])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        if name == "AssumptionEvidence":
            return _FakeQuery(self.evidence)
        return _FakeQuery()


def _call_freshness(
    *,
    project_id: int = 10,
    fresh_days: int = 14,
    aging_days: int = 45,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.get_evidence_freshness(
        project_id=project_id,
        fresh_days=fresh_days,
        aging_days=aging_days,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/evidence-freshness"
    assert "GET" in methods_by_path.get(path, set())


def test_freshness_ranks_queue_and_flags_stale() -> None:
    session = _FakeSession(
        assumptions=[_Assumption(100), _Assumption(101), _Assumption(102)],
        evidence=[
            # 100: evidence from June 2025 — stale under any clock.
            _Evidence(1, assumption_id=100, day=3),
        ],
    )
    response = _call_freshness(session=session)

    assert response.project_id == 10
    summary = response.summary
    assert summary.total_assumptions == 3
    assert summary.stale_count == 1
    assert summary.never_tested_count == 2
    assert summary.actionable_count == 3

    # Never-tested (101, 102) lead; stale 100 follows.
    order = [row.assumption_id for row in response.rows]
    assert order[-1] == 100
    assert {order[0], order[1]} == {101, 102}
    assert any(
        "never been tested" in text for text in response.recommendations
    )
    assert response.meta.model == "evidence_staleness_v1"


def test_custom_windows_flow_through() -> None:
    session = _FakeSession(
        assumptions=[_Assumption(100)],
        evidence=[
            _Evidence(
                1,
                assumption_id=100,
                created_at=datetime.now(UTC),
            )
        ],
    )
    response = _call_freshness(
        session=session, fresh_days=90, aging_days=180
    )

    row = response.rows[0]
    assert row.freshness == "FRESH"
    assert response.meta.fresh_days == 90
    assert response.meta.aging_days == 180


def test_inverted_windows_raise_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_freshness(fresh_days=45, aging_days=45)

    assert exc_info.value.status_code == 400
    assert "strictly less than" in exc_info.value.detail


def test_missing_project_raises_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_freshness(
            session=_FakeSession(project_missing=True),
        )

    assert exc_info.value.status_code == 404
