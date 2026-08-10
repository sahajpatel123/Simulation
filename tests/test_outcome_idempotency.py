"""Route/schema tests for idempotent outcome recording.

Founders integrating with the outcome endpoints (scheduled syncs, webhooks,
retry loops) can supply ``client_request_id`` so a retried submission never
creates a duplicate row: the first write wins and repeat submissions echo
the original record with a ``200`` (single) or ``replayed_count`` (batch).

These tests drive the route functions directly with a fake session (same
pattern as ``test_outcomes_batch_api.py``) so no Postgres or Redis is
required, plus a fake session that simulates the unique-index race.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.api.v1 import outcomes as out_mod
from app.schemas.outcome import (
    OutcomeBatchCreate,
    OutcomeBatchItem,
    OutcomeBatchOut,
    OutcomeCreate,
    OutcomeRecord,
)


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


class _Outcome:
    """Minimal outcome object exposing every field _hydrate_record reads."""

    def __init__(
        self,
        outcome_id: int,
        *,
        client_request_id: str | None = None,
        conversion: float = 0.05,
        mrr: float = 1000.0,
        simulation_id: int | None = None,
        predicted_conversion: float | None = 0.04,
        predicted_mrr: float | None = 900.0,
    ) -> None:
        self.id = outcome_id
        self.project_id = 10
        self.client_request_id = client_request_id
        self.actual_conversion_rate = conversion
        self.actual_mrr = mrr
        self.actual_cac = 50.0
        self.actual_churn_rate = 0.03
        self.days_since_launch = 30
        self.actual_dau = 120.0
        self.actual_nps = 42.0
        self.notes = "week one"
        self.predicted_conversion_rate = predicted_conversion
        self.predicted_mrr = predicted_mrr
        self.simulation_id = simulation_id
        self.variance_conversion = 25.0
        self.variance_mrr = 11.11
        self.variance_cac = None
        self.variance_churn = None
        self.calibration_score = 80.0
        self.created_at = datetime(2026, 8, 10, tzinfo=UTC)


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
    """Fake DB session; optional commit-race simulation via ``race_key``."""

    def __init__(
        self,
        *,
        project: _Project | None = None,
        simulations: list[_Simulation] | None = None,
        outcomes: list[_Outcome] | None = None,
        race_key: str | None = None,
    ) -> None:
        self.project = project or _Project()
        self.simulations = simulations if simulations is not None else []
        self.outcomes = outcomes if outcomes is not None else []
        self.added: list = []
        self.committed = 0
        self._next_id = 100
        self.race_key = race_key

    def query(self, model, *args, **kwargs) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([self.project])
        if name == "Simulation":
            return _FakeQuery(self.simulations)
        if name == "Outcome":
            return _FakeQuery(self.outcomes)
        return _FakeQuery([])

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    def commit(self) -> None:
        if self.race_key is not None and not getattr(self, "_raced", False):
            # Simulate a concurrent request inserting the winning key just
            # before our commit fires the unique-index violation.
            self._raced = True
            self.outcomes.append(
                _Outcome(
                    999,
                    client_request_id=self.race_key,
                )
            )
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        self.committed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)
        self.added = []

    def rollback(self) -> None:
        self.added = []

    def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 8, 10, tzinfo=UTC)


def _valid_row(*, key: str | None = None, conversion: float = 0.05) -> dict:
    row = {
        "actual_conversion_rate": conversion,
        "actual_mrr": 1000.0,
        "actual_cac": 50.0,
        "actual_churn_rate": 0.03,
        "days_since_launch": 30,
        "actual_dau": 120.0,
        "actual_nps": 42.0,
        "notes": "week one",
    }
    if key is not None:
        row["client_request_id"] = key
    return row


def _call_single(
    payload: dict,
    session: _FakeSession | None = None,
) -> tuple[OutcomeRecord, Response]:
    body = OutcomeCreate(**payload)
    db = session if session is not None else _FakeSession()
    response = Response()
    result = out_mod.record_outcome(
        project_id=10,
        payload=body,
        response=response,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )
    return result, response


def _call_batch(
    payload: dict,
    session: _FakeSession | None = None,
) -> OutcomeBatchOut:
    body = OutcomeBatchCreate(**payload)
    db = session if session is not None else _FakeSession()
    return out_mod.record_outcomes_batch(
        project_id=10,
        payload=body,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_client_request_id_normalised_and_validated() -> None:
    item = OutcomeCreate(**_valid_row(key="  launch-1  "))
    assert item.client_request_id == "launch-1"


def test_client_request_id_rejects_blank_and_whitespace() -> None:
    with pytest.raises(ValidationError):
        OutcomeCreate(**_valid_row(key="   "))
    with pytest.raises(ValidationError):
        OutcomeCreate(**_valid_row(key="launch one"))


def test_client_request_id_rejects_oversized_key() -> None:
    with pytest.raises(ValidationError):
        OutcomeCreate(**_valid_row(key="x" * 129))


def test_batch_item_inherits_idempotency_key() -> None:
    item = OutcomeBatchItem(**_valid_row(key="launch-2"))
    assert item.client_request_id == "launch-2"


# ---------------------------------------------------------------------------
# Single-record route
# ---------------------------------------------------------------------------


def test_single_replay_returns_original_without_new_row() -> None:
    existing = _Outcome(7, client_request_id="launch-1")
    session = _FakeSession(outcomes=[existing])

    result, response = _call_single(
        _valid_row(key="launch-1", conversion=0.99),
        session=session,
    )

    assert response.status_code == 200
    assert result.id == 7
    assert result.client_request_id == "launch-1"
    assert result.actual_conversion_rate == 0.05  # first write wins
    assert session.added == []
    assert session.committed == 0
    assert session.project.status == "ACTIVE"


def test_single_new_key_creates_row_with_key() -> None:
    session = _FakeSession(simulations=[_Simulation(9)])

    result, response = _call_single(
        _valid_row(key="launch-1"),
        session=session,
    )

    assert response.status_code == 201
    assert result.client_request_id == "launch-1"
    assert result.simulation_id == 9
    assert session.committed == 1
    assert session.project.status == "OUTCOME_RECORDED"


def test_single_without_key_creates_row_as_before() -> None:
    session = _FakeSession(simulations=[_Simulation(9)])

    result, response = _call_single(_valid_row(), session=session)

    assert response.status_code == 201
    assert result.client_request_id is None
    assert session.committed == 1


def test_single_race_returns_winner_as_replay() -> None:
    # The fake injects a concurrent winner at the first commit attempt,
    # so the route must roll back, re-query, and replay it with 200.
    session = _FakeSession(
        simulations=[_Simulation(9)],
        race_key="launch-1",
    )

    result, response = _call_single(
        _valid_row(key="launch-1"),
        session=session,
    )

    assert response.status_code == 200
    assert result.id == 999
    assert result.client_request_id == "launch-1"
    assert session.committed == 0


def test_single_race_without_winner_re_raises() -> None:
    class _AlwaysRaceSession(_FakeSession):
        def commit(self) -> None:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    with pytest.raises(IntegrityError):
        _call_single(
            _valid_row(key="launch-1"),
            session=_AlwaysRaceSession(simulations=[_Simulation(9)]),
        )


# ---------------------------------------------------------------------------
# Batch route
# ---------------------------------------------------------------------------


def test_batch_all_replayed_creates_nothing() -> None:
    existing = [
        _Outcome(7, client_request_id="k1"),
        _Outcome(8, client_request_id="k2"),
    ]
    session = _FakeSession(outcomes=existing)

    resp = _call_batch(
        {
            "outcomes": [
                _valid_row(key="k1"),
                _valid_row(key="k2", conversion=0.03),
            ]
        },
        session=session,
    )

    assert resp.created_count == 0
    assert resp.replayed_count == 2
    assert [o.id for o in resp.outcomes] == [7, 8]
    assert session.committed == 0
    assert session.added == []
    assert session.project.status == "ACTIVE"


def test_batch_mixed_replays_and_new_rows_preserves_order() -> None:
    existing = _Outcome(7, client_request_id="k1")
    session = _FakeSession(
        outcomes=[existing],
        simulations=[_Simulation(9)],
    )

    resp = _call_batch(
        {
            "outcomes": [
                _valid_row(key="k1"),
                _valid_row(key="k2", conversion=0.03),
                _valid_row(key="k3", conversion=0.07),
            ]
        },
        session=session,
    )

    assert resp.created_count == 2
    assert resp.replayed_count == 1
    assert [o.client_request_id for o in resp.outcomes] == ["k1", "k2", "k3"]
    assert resp.outcomes[0].id == 7
    assert resp.outcomes[1].id >= 100
    assert resp.outcomes[2].id >= 100
    assert session.committed == 1
    assert session.project.status == "OUTCOME_RECORDED"


def test_batch_rejects_duplicate_keys_within_payload() -> None:
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc:
        _call_batch(
            {
                "outcomes": [
                    _valid_row(key="k1"),
                    _valid_row(key="k1"),
                ]
            },
            session=session,
        )

    assert exc.value.status_code == 422
    assert "duplicate client_request_id" in exc.value.detail
    assert session.added == []
    assert session.committed == 0


def test_batch_without_keys_behaves_as_before() -> None:
    session = _FakeSession(simulations=[_Simulation(9)])

    resp = _call_batch(
        {"outcomes": [_valid_row(), _valid_row(conversion=0.03)]},
        session=session,
    )

    assert resp.created_count == 2
    assert resp.replayed_count == 0
    assert all(o.client_request_id is None for o in resp.outcomes)
    assert session.committed == 1


def test_batch_race_resolves_to_replay_and_retries_rest() -> None:
    session = _FakeSession(
        simulations=[_Simulation(9)],
        race_key="k1",
    )

    resp = _call_batch(
        {
            "outcomes": [
                _valid_row(key="k1"),
                _valid_row(key="k2", conversion=0.03),
            ]
        },
        session=session,
    )

    assert resp.created_count == 1
    assert resp.replayed_count == 1
    assert [o.client_request_id for o in resp.outcomes] == ["k1", "k2"]
    assert resp.outcomes[0].id == 999
    assert resp.outcomes[1].id >= 100
    assert session.committed == 1
