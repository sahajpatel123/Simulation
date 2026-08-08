"""Tests for user-initiated simulation cancellation.

Covers the three layers of the feature:

1. ``Conductor.run(cancel_check=...)`` stops between clusters and raises
   :class:`SimulationCancelled` instead of returning partial results.
2. The Celery task helpers detect a CANCELLED row and persist/notify the
   terminal state without touching failure metrics or webhook doubles.
3. ``POST /simulations/{id}/cancel`` revokes the Celery task, flips the
   row, broadcasts progress, and (for queued runs) emits the webhook.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.simulation.cancellation import SimulationCancelled
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


# ── Shared fakes ────────────────────────────────────────────────────────────


class _FakeSimulation:
    def __init__(
        self,
        *,
        sim_id: int = 1,
        project_id: int = 10,
        status: str = "QUEUED",
        task_id: str | None = "task-abc",
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.status = status
        self.task_id = task_id
        self.error_message: str | None = None
        self.results_json: dict | None = None
        self.consumer_volume = 10_000
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.updated_at = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, sims: list[_FakeSimulation]) -> None:
        self.sims = sims

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self) -> _FakeSimulation | None:
        return self.sims[0] if self.sims else None


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value

    def fetchone(self) -> object:
        return self._value


class _FakeSession:
    def __init__(
        self,
        sims: list[_FakeSimulation] | None = None,
        *,
        status_value: str = "CANCELLED",
        execute_error: Exception | None = None,
    ) -> None:
        self.sims = sims if sims is not None else []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[object] = []
        self._status_value = status_value
        self._execute_error = execute_error

    def query(self, *args, **kwargs):
        return _FakeQuery(self.sims)

    def execute(self, stmt, params=None):
        if self._execute_error is not None:
            raise self._execute_error
        return _FakeResult(self._status_value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, obj) -> None:
        self.refreshed.append(obj)


# ── Conductor cancellation ─────────────────────────────────────────────────


def test_conductor_cancel_check_raises_on_first_cluster() -> None:
    with pytest.raises(SimulationCancelled):
        Conductor().run(
            agents=[],
            env_params={
                "average_order_value": 999.0,
                "price_sensitivity": 0.5,
                "market_maturity": 0.3,
            },
            assumptions=[],
            product_type=ProductType.SAAS,
            cancel_check=lambda: True,
        )


def test_conductor_cancel_check_runs_once_per_cluster_until_true() -> None:
    calls = [0]

    def check() -> bool:
        calls[0] += 1
        return calls[0] >= 2

    with pytest.raises(SimulationCancelled):
        Conductor().run(
            agents=[],
            env_params={
                "average_order_value": 999.0,
                "price_sensitivity": 0.5,
                "market_maturity": 0.3,
            },
            assumptions=[],
            product_type=ProductType.SAAS,
            cancel_check=check,
        )
    assert calls[0] == 2


# ── Task-side helpers ──────────────────────────────────────────────────────


def test_simulation_is_cancelled_reads_fresh_status() -> None:
    from app.tasks import simulation_tasks as tasks_mod

    assert tasks_mod._simulation_is_cancelled(
        _FakeSession(status_value="CANCELLED"), 1
    ) is True
    assert tasks_mod._simulation_is_cancelled(
        _FakeSession(status_value="RUNNING"), 1
    ) is False


def test_simulation_is_cancelled_falls_back_safe_on_db_error() -> None:
    from app.tasks import simulation_tasks as tasks_mod

    session = _FakeSession(execute_error=RuntimeError("db blip"))
    assert tasks_mod._simulation_is_cancelled(session, 1) is False


def test_mark_cancelled_persists_and_notifies_without_failure_metrics(
    monkeypatch,
) -> None:
    from app.tasks import simulation_tasks as tasks_mod

    sim = _FakeSimulation(status="RUNNING")
    session = _FakeSession([sim])
    broadcasts: list[tuple] = []
    webhooks: list[tuple] = []
    cancelled_counter: list[int] = [0]

    monkeypatch.setattr(tasks_mod, "sync_broadcast", lambda *a, **k: broadcasts.append((a, k)))
    monkeypatch.setattr(
        tasks_mod,
        "_enqueue_simulation_webhooks",
        lambda *a, **k: webhooks.append((a, k)),
    )
    monkeypatch.setattr(
        tasks_mod.metrics,
        "sim_cancelled",
        lambda: cancelled_counter.__setitem__(0, cancelled_counter[0] + 1),
    )

    tasks_mod._mark_cancelled(session, sim, simulation_id=1)

    assert sim.status == "CANCELLED"
    assert sim.error_message == "Cancelled by user"
    assert session.commits >= 1
    assert cancelled_counter[0] == 1
    assert len(broadcasts) == 1
    assert broadcasts[0][0][1] == "CANCELLED"
    assert len(webhooks) == 1
    assert webhooks[0][1]["status"] == "CANCELLED"


# ── API endpoint ───────────────────────────────────────────────────────────


def _call_cancel_route(
    session: _FakeSession,
    *,
    user_id: int = 42,
    simulation_id: int = 1,
    monkeypatch,
):
    from app.api.v1 import simulations as sim_mod

    revoked: list[str] = []
    broadcasts: list[tuple] = []
    webhooks: list[tuple] = []
    invalidations: list[tuple] = []

    class _FakeControl:
        def revoke(self, task_id: str, terminate: bool) -> None:
            revoked.append(task_id)
            assert terminate is False

    monkeypatch.setattr(sim_mod.celery_app.control, "revoke", _FakeControl().revoke)
    monkeypatch.setattr(sim_mod, "sync_broadcast", lambda *a, **k: broadcasts.append((a, k)))
    monkeypatch.setattr(
        sim_mod,
        "_enqueue_simulation_webhooks",
        lambda *a, **k: webhooks.append((a, k)),
    )
    monkeypatch.setattr(
        sim_mod,
        "cache_invalidate",
        lambda namespace, user_id: invalidations.append((namespace, user_id)),
    )

    out = sim_mod.cancel_simulation(
        simulation_id=simulation_id,
        db=session,
        current_user=type("U", (), {"id": user_id})(),
    )
    return out, revoked, broadcasts, webhooks, invalidations


def test_cancel_queued_simulation(monkeypatch) -> None:
    sim = _FakeSimulation(status="QUEUED", task_id="task-queued")
    out, revoked, broadcasts, webhooks, invalidations = _call_cancel_route(
        _FakeSession([sim]), monkeypatch=monkeypatch
    )

    assert sim.status == "CANCELLED"
    assert sim.error_message == "Cancelled by user"
    assert out.status == "CANCELLED"
    assert out.simulation_id == 1
    assert out.message == "Simulation cancelled"
    assert revoked == ["task-queued"]
    assert broadcasts and broadcasts[0][0][1] == "CANCELLED"
    assert len(webhooks) == 1  # queued runs have no worker to emit the event
    assert invalidations


def test_cancel_running_simulation_defers_webhook_to_worker(monkeypatch) -> None:
    sim = _FakeSimulation(status="RUNNING", task_id="task-running")
    out, revoked, _broadcasts, webhooks, invalidations = _call_cancel_route(
        _FakeSession([sim]), monkeypatch=monkeypatch
    )

    assert out.status == "CANCELLED"
    assert revoked == ["task-running"]
    assert webhooks == []  # the running worker emits simulation.cancelled itself
    assert invalidations


def test_cancel_completed_simulation_conflicts(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_cancel_route(
            _FakeSession([_FakeSimulation(status="COMPLETED")]),
            monkeypatch=monkeypatch,
        )
    assert exc.value.status_code == 409


def test_cancel_failed_simulation_conflicts(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_cancel_route(
            _FakeSession([_FakeSimulation(status="FAILED")]),
            monkeypatch=monkeypatch,
        )
    assert exc.value.status_code == 409


def test_cancel_unowned_simulation_404(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        _call_cancel_route(
            _FakeSession([]),  # ownership join finds nothing
            monkeypatch=monkeypatch,
        )
    assert exc.value.status_code == 404


def test_cancel_proceeds_when_revoke_fails(monkeypatch) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(status="RUNNING", task_id="task-stuck")
    session = _FakeSession([sim])

    def failing_revoke(task_id: str, terminate: bool) -> None:
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(
        sim_mod.celery_app.control, "revoke", failing_revoke,
    )
    monkeypatch.setattr(sim_mod, "sync_broadcast", lambda *a, **k: None)
    monkeypatch.setattr(
        sim_mod, "_enqueue_simulation_webhooks", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        sim_mod, "cache_invalidate", lambda namespace, user_id: None,
    )

    out = sim_mod.cancel_simulation(
        simulation_id=1,
        db=session,
        current_user=type("U", (), {"id": 42})(),
    )
    assert out.status == "CANCELLED"
    assert sim.status == "CANCELLED"


def test_cancelled_progress_reports_zero(monkeypatch) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(status="CANCELLED", task_id=None)
    out = sim_mod.get_simulation_progress(
        simulation_id=1,
        db=_FakeSession([sim]),
        current_user=type("U", (), {"id": 42})(),
    )
    assert out["status"] == "CANCELLED"
    assert out["pct"] == 0
    assert out["results"] is None
