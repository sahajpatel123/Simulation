"""Route-level tests for ``POST /projects/{id}/outcomes/batch``.

The batch endpoint records multiple structured launch outcomes in one
transaction. These tests drive the route function directly with a fake
session (same pattern as ``test_outcomes_export_api.py``) so no Postgres
or Redis is required.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.outcome import OutcomeBatchCreate, OutcomeBatchOut


class _Project:
    def __init__(self, project_id: int = 10) -> None:
        self.id = project_id
        self.status = "ACTIVE"


class _Simulation:
    def __init__(
        self,
        sim_id: int,
        status: str = "COMPLETED",
        results: dict | None = None,
        *,
        created_at: datetime | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.results_json = (
            results
            if results is not None
            else {"mean_conversion_rate": 0.04, "mean_revenue": 900.0}
        )
        self.created_at = created_at or datetime(2026, 8, 1, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def filter(self, *args, **kwargs) -> _FakeQuery:
        return self

    def order_by(self, *args, **kwargs) -> _FakeQuery:
        return self

    def first(self) -> object | None:
        return self._items[0] if self._items else None

    def all(self) -> list:
        return list(self._items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _Project | None = None,
        simulations: list[_Simulation] | None = None,
    ) -> None:
        self.project = project or _Project()
        self.simulations = simulations if simulations is not None else []
        self.added: list = []
        self.committed = False
        self._next_id = 100

    def query(self, model, *args, **kwargs) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery(self.simulations)
        return _FakeQuery([])

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    def commit(self) -> None:
        self.committed = True
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)

    def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)


def _call_batch(
    payload: dict,
    session: _FakeSession | None = None,
) -> OutcomeBatchOut:
    from app.api.v1 import outcomes as out_mod

    body = OutcomeBatchCreate(**payload)
    db = session if session is not None else _FakeSession()
    return out_mod.record_outcomes_batch(
        project_id=10,
        payload=body,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _valid_row(
    *,
    conversion: float = 0.05,
    mrr: float = 1000.0,
    simulation_id: int | None = None,
) -> dict:
    return {
        "actual_conversion_rate": conversion,
        "actual_mrr": mrr,
        "actual_cac": 50.0,
        "actual_churn_rate": 0.03,
        "days_since_launch": 30,
        "actual_dau": 120.0,
        "actual_nps": 42.0,
        "notes": "week one",
        "simulation_id": simulation_id,
    }


def test_record_outcomes_batch_creates_all_rows_with_latest_sim() -> None:
    latest = _Simulation(9, created_at=datetime(2026, 8, 5, tzinfo=UTC))
    older = _Simulation(7, created_at=datetime(2026, 7, 1, tzinfo=UTC))
    session = _FakeSession(simulations=[latest, older])

    resp = _call_batch(
        {"outcomes": [_valid_row(), _valid_row(conversion=0.03, mrr=800.0)]},
        session=session,
    )

    assert resp.created_count == 2
    assert resp.project_id == 10
    assert len(resp.outcomes) == 2
    assert session.committed is True
    assert session.project.status == "OUTCOME_RECORDED"

    expected_variance = [25.0, -25.0]
    for outcome, expected_conv_variance in zip(resp.outcomes, expected_variance, strict=True):
        assert outcome.simulation_id == 9
        assert outcome.predicted_conversion_rate == 0.04
        assert outcome.predicted_mrr == 900.0
        assert outcome.variance.conversion == expected_conv_variance
        assert outcome.calibration_score > 0.0
        assert outcome.id >= 100


def test_record_outcomes_batch_uses_explicit_simulation_predictions() -> None:
    sim_low = _Simulation(
        7,
        results={"mean_conversion_rate": 0.02, "mean_revenue": 400.0},
    )
    sim_high = _Simulation(
        9,
        results={"mean_conversion_rate": 0.07, "mean_revenue": 1500.0},
    )
    session = _FakeSession(simulations=[sim_low, sim_high])

    resp = _call_batch(
        {
            "outcomes": [
                _valid_row(conversion=0.025, simulation_id=7),
                _valid_row(conversion=0.06, simulation_id=9),
            ]
        },
        session=session,
    )

    by_sim = {outcome.simulation_id: outcome for outcome in resp.outcomes}
    assert by_sim[7].predicted_conversion_rate == 0.02
    assert by_sim[7].variance.conversion == 25.0
    assert by_sim[9].predicted_conversion_rate == 0.07
    assert by_sim[9].variance.conversion == pytest.approx(-14.29, abs=0.01)


def test_record_outcomes_batch_missing_simulation_id_raises_400() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_batch(
            {"outcomes": [_valid_row(simulation_id=99)]},
            session=session,
        )

    assert exc.value.status_code == 400
    assert "simulation_ids not found" in exc.value.detail
    assert session.committed is False
    assert session.added == []


def test_record_outcomes_batch_rejects_non_completed_simulation() -> None:
    session = _FakeSession(
        simulations=[_Simulation(7, status="FAILED", results=None)]
    )

    with pytest.raises(HTTPException) as exc:
        _call_batch(
            {"outcomes": [_valid_row(simulation_id=7)]},
            session=session,
        )

    assert exc.value.status_code == 422
    assert "not completed with results" in exc.value.detail


def test_record_outcomes_batch_is_all_or_nothing() -> None:
    session = _FakeSession(simulations=[_Simulation(7)])

    with pytest.raises(HTTPException) as exc:
        _call_batch(
            {
                "outcomes": [
                    _valid_row(),
                    _valid_row(simulation_id=99),
                ]
            },
            session=session,
        )

    assert exc.value.status_code == 400
    assert session.added == []
    assert session.committed is False


def test_record_outcomes_batch_without_sims_records_unpredicted_rows() -> None:
    session = _FakeSession(simulations=[])

    resp = _call_batch(
        {"outcomes": [_valid_row(conversion=0.08)]},
        session=session,
    )

    outcome = resp.outcomes[0]
    assert outcome.simulation_id is None
    assert outcome.predicted_conversion_rate is None
    assert outcome.variance.conversion is None
    assert outcome.calibration_score == 50.0


def test_record_outcomes_batch_invalidates_caches(monkeypatch) -> None:
    from app.api.v1 import outcomes as out_mod

    invalidated: list[tuple[str, int]] = []

    def fake_invalidate(namespace: str, user_id: int) -> int:
        invalidated.append((namespace, user_id))
        return 0

    monkeypatch.setattr(out_mod, "cache_invalidate", fake_invalidate)
    session = _FakeSession(simulations=[_Simulation(7)])

    resp = _call_batch(
        {"outcomes": [_valid_row(), _valid_row()]},
        session=session,
    )

    assert resp.created_count == 2
    assert len(invalidated) == len(set(invalidated))
    assert all(user_id == 42 for _, user_id in invalidated)
    namespaces = {namespace for namespace, _ in invalidated}
    assert out_mod._OUTCOMES_DIGEST_CACHE_NAMESPACE in namespaces
    assert out_mod._NEXT_ACTION_CACHE_NAMESPACE in namespaces
    assert out_mod._USER_RECENT_OUTCOMES_CACHE_NAMESPACE in namespaces


def test_outcome_batch_schema_rejects_empty_list() -> None:
    with pytest.raises(ValidationError) as exc:
        OutcomeBatchCreate(outcomes=[])
    assert exc.value.errors()[0]["type"] == "too_short"


def test_outcome_batch_schema_rejects_invalid_row() -> None:
    with pytest.raises(ValidationError) as exc:
        OutcomeBatchCreate(
            outcomes=[{
                "actual_conversion_rate": 1.5,
                "actual_mrr": 1000.0,
                "actual_cac": 50.0,
                "actual_churn_rate": 0.03,
            }]
        )
    assert exc.value.errors()[0]["loc"][-1] == "actual_conversion_rate"


def test_outcome_batch_schema_caps_rows_at_100() -> None:
    rows = [
        {
            "actual_conversion_rate": 0.05,
            "actual_mrr": 1000.0,
            "actual_cac": 50.0,
            "actual_churn_rate": 0.03,
        }
        for _ in range(101)
    ]
    with pytest.raises(ValidationError) as exc:
        OutcomeBatchCreate(outcomes=rows)
    assert exc.value.errors()[0]["type"] == "too_long"
