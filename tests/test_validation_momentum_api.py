"""Route-level tests for the validation-momentum endpoint.

The endpoint is pure post-hoc analysis (no simulation required), so the
route tests use a fake session with assumption/evidence rows, mirroring the
validation-timeline route tests.
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


class _FakeAssumption:
    def __init__(self, assumption_id: int) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = "Pricing will be 999 rupees per month"
        self.category = "PricingArchitect"
        self.sensitivity = "HIGH"
        self.impact_score = 9.0
        self.is_hidden = False


class _FakeEvidence:
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


class _FakeProject:
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
        return self.items


class _FakeSession:
    def __init__(
        self,
        *,
        project: _FakeProject | None = None,
        project_missing: bool = False,
        assumptions: list | None = None,
        evidence: list | None = None,
    ) -> None:
        self.project = (
            None
            if project_missing
            else (project if project is not None else _FakeProject())
        )
        self.assumptions = (
            assumptions if assumptions is not None else [_FakeAssumption(100)]
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


def _call_momentum(
    *,
    project_id: int = 10,
    target_de_risked_pct: float = 1.0,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.get_validation_momentum(
        project_id=project_id,
        target_de_risked_pct=target_de_risked_pct,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_returns_momentum_payload() -> None:
    session = _FakeSession(
        assumptions=[_FakeAssumption(100), _FakeAssumption(101)],
        evidence=[
            _FakeEvidence(1, assumption_id=100, result="PASS", day=1),
            _FakeEvidence(2, assumption_id=101, result="PASS", day=8),
        ],
    )
    out = _call_momentum(session=session)
    assert out.project_id == 10
    assert out.counts.total_assumptions == 2
    assert out.counts.total_evidence_rows == 2
    assert out.counts.de_risked_count == 2
    assert out.counts.evidence_coverage_pct == 1.0
    assert out.forecast.target_de_risked_count == 2
    assert out.forecast.remaining_for_target == 0
    assert out.forecast.weeks_to_de_risked_target == 0.0
    assert out.forecast.confident is True
    assert out.velocity.first_evidence_at is not None
    assert out.meta["model"] == "validation_momentum_v1"


def test_route_honours_custom_target() -> None:
    session = _FakeSession(
        assumptions=[_FakeAssumption(i) for i in (100, 101, 102, 103)],
        evidence=[
            _FakeEvidence(1, assumption_id=100, result="PASS", day=1),
            _FakeEvidence(2, assumption_id=101, result="PASS", day=8),
            _FakeEvidence(3, assumption_id=102, result="PASS", day=15),
        ],
    )
    out = _call_momentum(target_de_risked_pct=0.5, session=session)
    assert out.counts.de_risked_count == 3
    assert out.forecast.target_de_risked_count == 3
    assert out.forecast.remaining_for_target == 0


def test_route_does_not_require_simulation() -> None:
    session = _FakeSession(
        assumptions=[_FakeAssumption(100)],
        evidence=[],
    )
    out = _call_momentum(session=session)
    assert out.counts.total_assumptions == 1
    assert out.counts.pending_count == 1
    assert out.velocity.trend == "NO_EVIDENCE"
    assert out.forecast.weeks_to_full_coverage is None


def test_route_missing_project_raises_404() -> None:
    session = _FakeSession(project_missing=True)
    with pytest.raises(HTTPException) as exc:
        _call_momentum(session=session)
    assert exc.value.status_code == 404


def test_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    assert "GET" in methods_by_path.get(
        "/projects/{project_id}/validation-momentum",
        set(),
    )
