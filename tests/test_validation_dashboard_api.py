"""Route-level tests for the /projects/{id}/validation-dashboard endpoint.

The dashboard composes the evidence digest, timeline milestones, and
validation momentum into one response. These tests use a fake session
mirroring the momentum/timeline API tests, verifying that each sub-payload
is populated and that the route is registered.
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
        result: str = "PASS",
        day: int = 3,
    ) -> None:
        self.id = evidence_id
        self.project_id = 10
        self.assumption_id = assumption_id
        self.method = "WILLINGNESS_TO_PAY_SURVEY"
        self.result = result
        self.observed_metric = 0.42 if result == "PASS" else 0.02
        self.notes = "35 responses"
        self.created_at = datetime(2026, 1, day, tzinfo=UTC)


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


def _call_dashboard(
    *,
    project_id: int = 10,
    target_de_risked_pct: float = 1.0,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.get_validation_dashboard(
        project_id=project_id,
        target_de_risked_pct=target_de_risked_pct,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_dashboard_combines_all_three_sub_payloads() -> None:
    session = _FakeSession(
        assumptions=[_Assumption(100), _Assumption(101)],
        evidence=[
            _Evidence(1, assumption_id=100, result="PASS", day=1),
            _Evidence(2, assumption_id=101, result="PASS", day=8),
        ],
    )
    out = _call_dashboard(session=session)

    # Top-level
    assert out.project_id == 10

    # Evidence digest populated
    digest = out.evidence_digest
    assert digest.project_id == 10
    assert digest.total_assumptions == 2
    assert digest.total_evidence_rows == 2
    assert digest.de_risked_count == 2
    assert digest.evidence_coverage_pct == 1.0
    assert digest.next_action != ""

    # Timeline milestones populated
    milestones = out.timeline_milestones
    assert milestones.first_evidence_event_id == 1
    assert milestones.first_de_risked_event_id == 1
    assert milestones.last_evidence_event_id == 2

    # Momentum populated
    momentum = out.momentum
    assert momentum.project_id == 10
    assert momentum.counts.total_assumptions == 2
    assert momentum.counts.de_risked_count == 2
    assert momentum.forecast.confident is True
    assert momentum.velocity.trend in ("STEADY", "DECELERATING", "ACCELERATING")

    # Meta
    assert out.meta["model"] == "validation_dashboard_v2"


def test_dashboard_composes_evidence_freshness() -> None:
    """Freshness rollup joins the payload; never-tested leads the queue."""
    session = _FakeSession(
        assumptions=[_Assumption(100), _Assumption(101)],
        evidence=[
            _Evidence(1, assumption_id=100, result="PASS", day=1),
            _Evidence(2, assumption_id=101, result="PASS", day=8),
        ],
    )
    out = _call_dashboard(session=session)

    summary = out.evidence_freshness
    assert summary is not None
    assert summary.total_assumptions == 2
    assert summary.tested_assumptions == 2
    assert "evidence-freshness" in out.meta["source"]


def test_dashboard_retest_queue_leads_with_never_tested() -> None:
    """The queue's head is clock-independent: never-tested always leads."""
    session = _FakeSession(
        assumptions=[_Assumption(100), _Assumption(101)],
        evidence=[
            _Evidence(1, assumption_id=100, result="PASS", day=1),
        ],
    )
    out = _call_dashboard(session=session)

    assert out.evidence_freshness is not None
    assert out.evidence_freshness.never_tested_count == 1
    assert len(out.retest_queue_top) >= 1
    assert out.retest_queue_top[0].assumption_id == 101
    assert out.retest_queue_top[0].freshness == "NEVER_TESTED"


def test_dashboard_without_evidence_has_empty_queue() -> None:
    session = _FakeSession(
        assumptions=[],
        evidence=[],
    )
    out = _call_dashboard(session=session)

    assert out.evidence_freshness is not None
    assert out.evidence_freshness.total_assumptions == 0
    assert out.retest_queue_top == []


def test_dashboard_honours_custom_target() -> None:
    """With 3 of 4 de-risked, a 50 % target (2) is bumped to 3 so remaining is 0."""
    session = _FakeSession(
        assumptions=[_Assumption(i) for i in (100, 101, 102, 103)],
        evidence=[
            _Evidence(1, assumption_id=100, result="PASS", day=1),
            _Evidence(2, assumption_id=101, result="PASS", day=8),
            _Evidence(3, assumption_id=102, result="PASS", day=15),
        ],
    )
    out_full = _call_dashboard(target_de_risked_pct=1.0, session=session)
    out_partial = _call_dashboard(target_de_risked_pct=0.5, session=session)
    # 50 % of 4 = 2, but 3 are already de-risked → target bumped to 3.
    assert out_partial.momentum.forecast.target_de_risked_count == 3
    assert out_partial.momentum.forecast.remaining_for_target == 0
    # 100 % of 4 = 4, 3 de-risked → 1 remaining.
    assert out_full.momentum.forecast.target_de_risked_count == 4
    assert out_full.momentum.forecast.remaining_for_target == 1


def test_dashboard_does_not_require_simulation() -> None:
    session = _FakeSession(
        assumptions=[_Assumption(100)],
        evidence=[],
    )
    out = _call_dashboard(session=session)
    assert out.evidence_digest.total_assumptions == 1
    assert out.evidence_digest.pending_count == 1
    assert out.momentum.velocity.trend == "NO_EVIDENCE"
    assert out.timeline_milestones.first_evidence_event_id is None


def test_dashboard_missing_project_raises_404() -> None:
    session = _FakeSession(project_missing=True)
    with pytest.raises(HTTPException) as exc:
        _call_dashboard(session=session)
    assert exc.value.status_code == 404


def test_dashboard_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    assert "GET" in methods_by_path.get(
        "/projects/{project_id}/validation-dashboard",
        set(),
    )
