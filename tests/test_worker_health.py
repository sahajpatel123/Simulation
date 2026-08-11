"""Tests for the Celery worker-health digest endpoint.

Covers the pure digest builder in ``app.core.worker_health`` (verdicts,
totals, broker status, queue rows), the live collector with fake Celery
``Inspect`` / Redis broker objects, the Prometheus queue-depth gauges, and
the route contract. These run without a live worker or broker.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1 import system_health as system_health_module  # noqa: E402
from app.core.metrics import metrics
from app.core.worker_health import (  # noqa: E402
    REASON_BROKER_UNREACHABLE,
    REASON_NO_WORKERS,
    REASON_QUEUE_BACKLOG,
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
    build_worker_health,
    collect_worker_snapshot,
    record_worker_gauges,
)
from app.schemas.system_health import WorkerHealthOut  # noqa: E402


def _worker(hostname: str = "celery@w1", **overrides: Any) -> dict[str, Any]:
    row = {
        "hostname": hostname,
        "concurrency": 4,
        "pid": 123,
        "prefetch_count": 16,
        "uptime_seconds": 3600,
        "active_tasks": 0,
        "reserved_tasks": 0,
        "scheduled_tasks": 0,
    }
    row.update(overrides)
    return row


def _queue(name: str = "celery", **overrides: Any) -> dict[str, Any]:
    row = {
        "name": name,
        "depth": 0,
        "active_tasks": 0,
        "reserved_tasks": 0,
        "scheduled_tasks": 0,
    }
    row.update(overrides)
    return row


def _broker(**overrides: Any) -> dict[str, Any]:
    row = {"status": "ok", "scheme": "redis", "database": 0, "error": None}
    row.update(overrides)
    return row


def _valid_snapshot(
    *,
    workers_online: int = 1,
    workers: list[dict[str, Any]] | None = None,
    queues: list[dict[str, Any]] | None = None,
    broker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if workers is not None:
        workers_online = len(workers)
    return {
        "workers_online": workers_online,
        "workers": workers or [_worker()],
        "queues": queues or [_queue()],
        "broker": broker or _broker(),
    }


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Each test gets a fresh metrics registry so gauges don't leak."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    yield


def test_healthy_digest_aggregates_totals_and_schema() -> None:
    payload = build_worker_health(
        **_valid_snapshot(
            workers=[
                _worker(active_tasks=2, reserved_tasks=1),
                _worker(
                    hostname="celery@w2",
                    active_tasks=1,
                    scheduled_tasks=3,
                ),
            ],
            queues=[
                _queue(depth=5, active_tasks=2, reserved_tasks=1),
                _queue(
                    name="simulation",
                    depth=1,
                    active_tasks=1,
                    scheduled_tasks=3,
                ),
            ],
        ),
        generated_at="now",
    )

    assert payload["generated_at"] == "now"
    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["reasons"] == []
    assert payload["broker"] == {
        "status": "ok",
        "scheme": "redis",
        "database": 0,
        "error": None,
    }
    assert payload["totals"] == {
        "workers_online": 2,
        "active_tasks": 3,
        "reserved_tasks": 1,
        "scheduled_tasks": 3,
        "queue_depth": 6,
    }
    assert [row["hostname"] for row in payload["workers"]] == [
        "celery@w1",
        "celery@w2",
    ]
    assert [row["name"] for row in payload["queues"]] == [
        "celery",
        "simulation",
    ]
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_no_workers_with_reachable_broker_is_degraded() -> None:
    payload = build_worker_health(
        **_valid_snapshot(workers_online=0, workers=[]),
        generated_at="now",
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["reasons"] == [REASON_NO_WORKERS]
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_unconfigured_broker_without_workers_is_no_data() -> None:
    payload = build_worker_health(
        **_valid_snapshot(
            workers_online=0,
            workers=[],
            broker=_broker(status="unconfigured", scheme=""),
        ),
        generated_at="now",
    )

    assert payload["verdict"] == VERDICT_NO_DATA
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_backlog_above_threshold_is_watch() -> None:
    payload = build_worker_health(
        **_valid_snapshot(queues=[_queue(depth=25)]),
        backlog_threshold=10,
        generated_at="now",
    )

    assert payload["verdict"] == VERDICT_WATCH
    assert payload["reasons"] == [REASON_QUEUE_BACKLOG]
    assert payload["totals"]["queue_depth"] == 25
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_broker_error_beats_every_other_signal() -> None:
    payload = build_worker_health(
        **_valid_snapshot(
            workers_online=0,
            workers=[],
            broker=_broker(
                status="error",
                error="connection refused",
            ),
        ),
        backlog_threshold=0,
        generated_at="now",
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["reasons"] == [REASON_BROKER_UNREACHABLE]
    assert payload["broker"]["error"] == "connection refused"
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


class _FakeInspect:
    """Minimal Celery ``Inspect`` stand-in with per-worker state."""

    def __init__(self, workers: dict[str, dict[str, Any]]) -> None:
        self.workers = workers

    def ping(self) -> dict[str, dict[str, str]]:
        return {host: {"ok": "pong"} for host in self.workers}

    def stats(self) -> dict[str, dict[str, Any]]:
        return {
            host: state["stats"]
            for host, state in self.workers.items()
        }

    def active(self) -> dict[str, list[dict[str, Any]]]:
        return {
            host: state["active"]
            for host, state in self.workers.items()
        }

    def reserved(self) -> dict[str, list[dict[str, Any]]]:
        return {
            host: state["reserved"]
            for host, state in self.workers.items()
        }

    def scheduled(self) -> dict[str, list[dict[str, Any]]]:
        return {
            host: state["scheduled"]
            for host, state in self.workers.items()
        }

    def active_queues(self) -> dict[str, list[dict[str, str]]]:
        return {
            host: state["queues"]
            for host, state in self.workers.items()
        }


class _BrokenInspect(_FakeInspect):
    """Inspect whose per-probe methods fail independently."""

    def __init__(self, *, fail_active: bool = False) -> None:
        super().__init__({})
        self.fail_active = fail_active

    def active(self) -> dict[str, list[dict[str, Any]]]:
        if self.fail_active:
            raise RuntimeError("control command failed")
        return {}


class _FakeBroker:
    def __init__(self, depths: dict[str, int]) -> None:
        self.depths = depths

    def ping(self) -> bool:
        return True

    def llen(self, name: str) -> int:
        return self.depths.get(name, 0)


_SAMPLE_WORKERS: dict[str, dict[str, Any]] = {
    "celery@worker-a": {
        "stats": {
            "pid": 1001,
            "prefetch_count": 8,
            "uptime": 7200,
            "pool": {"max-concurrency": 2},
        },
        "active": [
            {
                "id": "t1",
                "name": "simulation.run",
                "delivery_info": {"routing_key": "celery"},
            }
        ],
        "reserved": [
            {
                "id": "t2",
                "name": "simulation.run",
                "delivery_info": {"routing_key": "simulation"},
            }
        ],
        "scheduled": [],
        "queues": [{"name": "celery"}, {"name": "simulation"}],
    },
    "celery@worker-b": {
        "stats": {
            "pid": 1002,
            "pool": {"max-concurrency": 4},
        },
        "active": [
            {
                "id": "t3",
                "name": "simulation.run",
                "delivery_info": {"routing_key": "simulation"},
            }
        ],
        "reserved": [],
        "scheduled": [
            {
                "id": "t4",
                "name": "retention.email",
                "request": {
                    "delivery_info": {"routing_key": "simulation"},
                },
            }
        ],
        "queues": [{"name": "simulation"}],
    },
}


def test_collect_worker_snapshot_parses_workers_and_queues() -> None:
    snapshot = collect_worker_snapshot(
        inspect=_FakeInspect(_SAMPLE_WORKERS),
        broker_client=_FakeBroker({"celery": 3, "simulation": 7}),
    )

    assert snapshot["workers_online"] == 2
    assert [w["hostname"] for w in snapshot["workers"]] == [
        "celery@worker-a",
        "celery@worker-b",
    ]
    worker_a = snapshot["workers"][0]
    assert worker_a["concurrency"] == 2
    assert worker_a["pid"] == 1001
    assert worker_a["prefetch_count"] == 8
    assert worker_a["uptime_seconds"] == 7200
    assert worker_a["active_tasks"] == 1
    assert worker_a["reserved_tasks"] == 1
    worker_b = snapshot["workers"][1]
    assert worker_b["concurrency"] == 4
    assert worker_b["active_tasks"] == 1
    assert worker_b["scheduled_tasks"] == 1

    assert snapshot["broker"]["status"] == "ok"
    assert [q["name"] for q in snapshot["queues"]] == [
        "celery",
        "simulation",
    ]
    assert snapshot["queues"][0]["depth"] == 3
    assert snapshot["queues"][0]["active_tasks"] == 1
    assert snapshot["queues"][1]["depth"] == 7
    assert snapshot["queues"][1]["active_tasks"] == 1
    assert snapshot["queues"][1]["reserved_tasks"] == 1
    assert snapshot["queues"][1]["scheduled_tasks"] == 1

    payload = build_worker_health(**snapshot, generated_at="now")
    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["totals"]["queue_depth"] == 10
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_collector_tolerates_failed_probes_and_missing_broker() -> None:
    snapshot = collect_worker_snapshot(
        inspect=_BrokenInspect(fail_active=True),
        broker_client=None,
    )

    assert snapshot["workers_online"] == 0
    assert snapshot["workers"] == []
    assert snapshot["queues"] == [
        {
            "name": "celery",
            "depth": None,
            "active_tasks": 0,
            "reserved_tasks": 0,
            "scheduled_tasks": 0,
        }
    ]
    assert snapshot["broker"]["status"] == "unconfigured"

    payload = build_worker_health(**snapshot, generated_at="now")
    assert payload["verdict"] == VERDICT_NO_DATA
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_collector_clamps_invalid_concurrency_to_none() -> None:
    workers = {
        "celery@w": {
            "stats": {"pool": {"max-concurrency": 0}},
            "active": [],
            "reserved": [],
            "scheduled": [],
            "queues": [{"name": "celery"}],
        }
    }
    snapshot = collect_worker_snapshot(
        inspect=_FakeInspect(workers),
        broker_client=_FakeBroker({"celery": 0}),
    )

    assert snapshot["workers"][0]["concurrency"] is None
    payload = build_worker_health(**snapshot, generated_at="now")
    assert payload["verdict"] == VERDICT_HEALTHY
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)


def test_record_worker_gauges_mirrors_snapshot_into_metrics() -> None:
    snapshot = collect_worker_snapshot(
        inspect=_FakeInspect(_SAMPLE_WORKERS),
        broker_client=_FakeBroker({"celery": 3, "simulation": 7}),
    )

    record_worker_gauges(snapshot)
    rendered = metrics.render()

    assert "thecee_celery_workers_online 2" in rendered
    assert 'thecee_celery_queue_depth{queue="celery"} 3' in rendered
    assert 'thecee_celery_queue_depth{queue="simulation"} 7' in rendered


def test_worker_health_route_contract(monkeypatch) -> None:
    snapshot = _valid_snapshot(
        workers=[_worker(active_tasks=1)],
        queues=[_queue(depth=4, active_tasks=1)],
    )
    monkeypatch.setattr(
        system_health_module.worker_health_module,
        "get_broker_client",
        lambda: None,
    )
    monkeypatch.setattr(
        system_health_module.worker_health_module,
        "collect_worker_snapshot",
        lambda **kwargs: snapshot,
    )

    payload = system_health_module.worker_health(backlog_threshold=10)

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["totals"]["queue_depth"] == 4
    assert isinstance(WorkerHealthOut(**payload), WorkerHealthOut)
