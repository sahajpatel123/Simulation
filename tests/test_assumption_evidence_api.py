"""Route-level tests for the assumption-evidence log and scorecard endpoints.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.schemas.assumption_evidence import EvidenceCreate

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


PRICING_TEXT = "We believe pricing will be 999 rupees per month for this"


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        signal_quality: float | None = 0.62,
        environment_id: int | None = 7,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.signal_quality = signal_quality
        self.environment_id = environment_id
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.05,
                "mean_conversion_rate": 0.05,
                "mean_revenue": 999.0,
                "total_agents": 10000,
                "converted": 500,
                "product_type_detected": "saas",
            }
        )


class _FakeEnvironment:
    def __init__(self) -> None:
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0


class _FakeAssumption:
    def __init__(
        self,
        assumption_id: int,
        text: str = PRICING_TEXT,
        category: str = "PricingArchitect",
    ) -> None:
        self.id = assumption_id
        self.project_id = 10
        self.text = text
        self.category = category
        self.sensitivity = "CRITICAL"
        self.impact_score = 9.0
        self.is_hidden = False


class _FakeEvidence:
    def __init__(
        self,
        evidence_id: int,
        *,
        result: str = "PASS",
        day: int = 5,
    ) -> None:
        self.id = evidence_id
        self.project_id = 10
        self.assumption_id = 100
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

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    _NO_PROJECT = object()

    def __init__(
        self,
        *,
        project: _FakeProject | object = _NO_PROJECT,
        sim: _FakeSimulation | None = None,
        env: _FakeEnvironment | None = None,
        assumptions: list | None = None,
        evidence: list | None = None,
    ) -> None:
        self.project = project if project is not self._NO_PROJECT else _FakeProject()
        self.sim = sim
        self.env = env if env is not None else _FakeEnvironment()
        self.assumptions = (
            assumptions if assumptions is not None else [_FakeAssumption(100)]
        )
        self.evidence = evidence if evidence is not None else []
        self.added: list = []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project is self._NO_PROJECT:
                return _FakeQuery([])
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Environment":
            return _FakeQuery([self.env] if self.env is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        if name == "AssumptionEvidence":
            return _FakeQuery(self.evidence)
        return _FakeQuery()

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 500

    def refresh(self, obj) -> None:
        return None


class _MissingProjectSession(_FakeSession):
    """Fake session whose Project query returns no rows."""

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([])
        return super().query(model, *args, **kwargs)


def _call_create(
    *,
    project_id: int = 10,
    assumption_id: int = 100,
    payload: EvidenceCreate | None = None,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.create_assumption_evidence(
        project_id=project_id,
        assumption_id=assumption_id,
        payload=payload
        or EvidenceCreate(method="WILLINGNESS_TO_PAY_SURVEY", result="PASS"),
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _call_scorecard(
    *,
    project_id: int = 10,
    assumption_id: int = 100,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.get_assumption_evidence_scorecard(
        project_id=project_id,
        assumption_id=assumption_id,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _call_digest(
    *,
    project_id: int = 10,
    session: _FakeSession | None = None,
):
    from app.api.v1 import assumption_evidence as ev_mod

    db = session or _FakeSession()
    return ev_mod.get_assumption_evidence_digest(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


class TestCreateEvidence:
    def test_pass_returns_derived_confidence(self) -> None:
        out = _call_create()
        assert out.id == 500
        assert out.assumption_id == 100
        assert out.assumption_text == PRICING_TEXT
        assert out.result == "PASS"
        assert out.derived_confidence == "VALIDATED_INTERNAL"
        assert out.method_label == "Willingness-to-pay survey"

    def test_fail_returns_aspirational(self) -> None:
        out = _call_create(
            payload=EvidenceCreate(
                method="LANDING_PAGE_SMOKE_TEST", result="FAIL", observed_metric=0.01
            )
        )
        assert out.result == "FAIL"
        assert out.derived_confidence == "ASPIRATIONAL"
        assert out.observed_metric == 0.01

    def test_unknown_assumption_raises_404(self) -> None:
        session = _FakeSession(assumptions=[])
        with pytest.raises(HTTPException) as exc:
            _call_create(session=session)
        assert exc.value.status_code == 404

    def test_project_not_owned_raises_404(self) -> None:
        session = _FakeSession(project=_FakeSession._NO_PROJECT, assumptions=[])
        with pytest.raises(HTTPException) as exc:
            _call_create(session=session)
        assert exc.value.status_code == 404


class TestScorecard:
    def test_completed_simulation_with_evidence(self) -> None:
        session = _FakeSession(
            sim=_FakeSimulation(),
            evidence=[
                _FakeEvidence(1, result="INCONCLUSIVE", day=2),
                _FakeEvidence(2, result="PASS", day=6),
            ],
        )
        out = _call_scorecard(session=session)
        assert out.project_id == 10
        assert out.assumption_id == 100
        assert out.evidence_count == 2
        assert out.latest_result == "PASS"
        assert out.derived_confidence == "VALIDATED_INTERNAL"
        assert out.validation_roi_before is not None
        assert out.validation_roi_after is not None
        assert out.validation_roi_after < out.validation_roi_before
        assert [e.id for e in out.history] == [2, 1]
        assert out.meta["model"] == "evidence_scorecard_v1"


class TestEvidenceDigest:
    def test_project_level_summary(self) -> None:
        session = _FakeSession(
            assumptions=[
                _FakeAssumption(100),
                _FakeAssumption(101),
                _FakeAssumption(102),
            ],
            evidence=[
                _FakeEvidence(1, result="PASS", day=3),
                _FakeEvidence(2, result="INCONCLUSIVE", day=4),
            ],
        )
        out = _call_digest(session=session)
        assert out.project_id == 10
        assert out.total_assumptions == 3
        assert out.total_evidence_rows == 2
        assert out.assumptions_with_evidence == 1
        assert out.de_risked_count == 1
        assert out.inconclusive_count == 0
        assert out.pending_count == 2
        assert out.result_counts == {
            "PASS": 1,
            "FAIL": 0,
            "INCONCLUSIVE": 1,
        }
        assert {row.assumption_id for row in out.assumptions} == {
            100,
            101,
            102,
        }

    def test_digest_does_not_require_simulation(self) -> None:
        session = _FakeSession(
            assumptions=[_FakeAssumption(100)],
            evidence=[],
            sim=None,
        )
        out = _call_digest(session=session)
        assert out.total_assumptions == 1
        assert out.pending_count == 1

    def test_digest_project_not_owned_raises_404(self) -> None:
        session = _MissingProjectSession()
        with pytest.raises(HTTPException) as exc:
            _call_digest(session=session)
        assert exc.value.status_code == 404

    def test_no_evidence_returns_zero_state(self) -> None:
        out = _call_scorecard(session=_FakeSession(sim=_FakeSimulation()))
        assert out.evidence_count == 0
        assert out.derived_confidence is None
        assert out.validation_roi_before == out.validation_roi_after

    def test_no_completed_simulation_raises_409(self) -> None:
        session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
        with pytest.raises(HTTPException) as exc:
            _call_scorecard(session=session)
        assert exc.value.status_code == 409

    def test_empty_results_raises_422(self) -> None:
        session = _FakeSession(sim=_FakeSimulation(results={}))
        with pytest.raises(HTTPException) as exc:
            _call_scorecard(session=session)
        assert exc.value.status_code == 422

    def test_unknown_assumption_raises_404(self) -> None:
        session = _FakeSession(sim=_FakeSimulation(), assumptions=[])
        with pytest.raises(HTTPException) as exc:
            _call_scorecard(session=session)
        assert exc.value.status_code == 404
