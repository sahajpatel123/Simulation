"""Tests for the one-call system overview endpoint.

Covers the pure composition builder in ``app.core.system_overview``
(verdicts, summaries, headlines, service derivation, overall status) and
the route contract that wires every individual health digest into it.
These run without a live database, Redis or Celery worker.
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
from app.core.system_overview import (  # noqa: E402
    REQUEST_DEGRADED_ERROR_RATE,
    REQUEST_WATCH_ERROR_RATE,
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_UNCONFIGURED,
    VERDICT_WATCH,
    build_system_overview,
)
from app.schemas.system_health import SystemOverviewOut  # noqa: E402


def _digests(
    *,
    request: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    llm: dict[str, Any] | None = None,
    cache: dict[str, Any] | None = None,
    worker: dict[str, Any] | None = None,
    simulation: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "request": request
        or {
            "total_requests": 10,
            "overall_error_rate": 0.0,
            "route_count": 3,
        },
        "query": query
        or {
            "total_queries": 50,
            "error_rate": 0.0,
            "slow_query_count": 0,
            "verdict": VERDICT_HEALTHY,
        },
        "llm": llm
        or {
            "total_attempts": 20,
            "success_rate": 1.0,
            "failure_count": 0,
            "verdict": VERDICT_HEALTHY,
        },
        "cache": cache
        or {
            "total_reads": 30,
            "hit_rate": 0.8,
            "current_keys": 12,
            "verdict": VERDICT_HEALTHY,
        },
        "worker": worker
        or {
            "verdict": VERDICT_HEALTHY,
            "reasons": [],
            "broker": {
                "status": "ok",
                "scheme": "redis",
                "database": 0,
                "error": None,
            },
            "totals": {
                "workers_online": 2,
                "active_tasks": 1,
                "reserved_tasks": 0,
                "scheduled_tasks": 0,
                "queue_depth": 3,
            },
            "workers": [],
            "queues": [],
        },
        "simulation": simulation
        or {
            "verdict": VERDICT_HEALTHY,
            "reasons": [],
            "total_simulations": 4,
            "completion_rate": 1.0,
            "failed_count": 0,
        },
    }


def _services(**overrides: Any) -> dict[str, Any]:
    services = {
        "database": {"status": "ok", "latency_ms": 1.2, "error": None},
        "redis": {"status": "ok", "latency_ms": 0.8, "error": None},
    }
    services.update(overrides)
    return services


def _build(**kwargs: Any) -> dict[str, Any]:
    overrides = dict(kwargs)
    services = overrides.pop("services", None)
    return build_system_overview(
        **_digests(),
        services=services if services is not None else _services(),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Overall verdicts
# ---------------------------------------------------------------------------


def test_all_healthy_digests_produce_ok_overview_and_schema() -> None:
    payload = _build()

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    assert payload["unhealthy_components"] == []
    assert [row["key"] for row in payload["subsystems"]] == [
        "request",
        "query",
        "llm",
        "cache",
        "worker",
        "simulation",
    ]
    assert all(row["healthy"] for row in payload["subsystems"])
    assert isinstance(SystemOverviewOut(**payload), SystemOverviewOut)


def test_no_data_and_unconfigured_verdicts_count_as_healthy() -> None:
    digests = _digests(
        request={"total_requests": 0, "overall_error_rate": None},
        query={"verdict": VERDICT_NO_DATA},
        llm={"verdict": VERDICT_NO_DATA},
        cache={"verdict": VERDICT_UNCONFIGURED, "total_reads": 0},
        worker={
            "verdict": VERDICT_NO_DATA,
            "reasons": [],
            "broker": {
                "status": "unconfigured",
                "scheme": "",
                "database": None,
                "error": None,
            },
            "totals": {
                "workers_online": 0,
                "active_tasks": 0,
                "reserved_tasks": 0,
                "scheduled_tasks": 0,
                "queue_depth": 0,
            },
        },
        simulation={"verdict": VERDICT_NO_DATA},
    )

    payload = build_system_overview(
        **digests,
        services=_services(),
        generated_at="now",
    )

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    assert payload["unhealthy_components"] == []
    assert isinstance(SystemOverviewOut(**payload), SystemOverviewOut)


def test_watch_subsystem_marks_overall_degraded() -> None:
    digests = _digests(
        simulation={
            "verdict": VERDICT_WATCH,
            "reasons": ["failure_rate_high"],
            "total_simulations": 10,
            "completion_rate": 0.9,
            "failed_count": 1,
        }
    )

    payload = build_system_overview(**digests, services=_services())

    assert payload["status"] == "degraded"
    assert payload["healthy"] is False
    assert payload["unhealthy_components"] == ["simulation"]


def test_service_error_marks_overall_degraded() -> None:
    payload = _build(
        services=_services(
            database={"status": "error", "latency_ms": None, "error": "down"}
        )
    )

    assert payload["status"] == "degraded"
    assert payload["healthy"] is False
    assert payload["unhealthy_components"] == ["database"]


# ---------------------------------------------------------------------------
# Request verdict derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error_rate", "expected"),
    [
        (0.0, VERDICT_HEALTHY),
        (REQUEST_WATCH_ERROR_RATE, VERDICT_HEALTHY),
        (0.02, VERDICT_WATCH),
        (REQUEST_DEGRADED_ERROR_RATE, VERDICT_WATCH),
        (0.5, VERDICT_DEGRADED),
    ],
)
def test_request_verdict_derived_from_error_rate(
    error_rate: float,
    expected: str,
) -> None:
    digests = _digests(
        request={
            "total_requests": 100,
            "overall_error_rate": error_rate,
            "route_count": 4,
        }
    )

    payload = build_system_overview(**digests, services=_services())
    request_row = next(
        row for row in payload["subsystems"] if row["key"] == "request"
    )
    assert request_row["verdict"] == expected


def test_request_no_data_when_no_traffic() -> None:
    digests = _digests(
        request={"total_requests": 0, "overall_error_rate": None}
    )
    payload = build_system_overview(**digests, services=_services())
    request_row = next(
        row for row in payload["subsystems"] if row["key"] == "request"
    )

    assert request_row["verdict"] == VERDICT_NO_DATA
    assert request_row["healthy"] is True
    assert request_row["summary"] == "No HTTP request traffic recorded yet"


# ---------------------------------------------------------------------------
# Summaries and headlines
# ---------------------------------------------------------------------------


def test_subsystem_summaries_and_headlines() -> None:
    payload = _build()
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["request"]["summary"] == (
        "10 request(s), 0.0% error rate"
    )
    assert by_key["request"]["headline"] == {
        "total_requests": 10,
        "error_rate": 0.0,
        "route_count": 3,
    }

    assert by_key["query"]["summary"] == (
        "50 queries, 0.0% error rate, 0 slow"
    )
    assert by_key["query"]["headline"] == {
        "total_queries": 50,
        "error_rate": 0.0,
        "slow_query_count": 0,
    }

    assert by_key["llm"]["summary"] == "20 attempt(s), 100.0% success"
    assert by_key["llm"]["headline"] == {
        "total_attempts": 20,
        "success_rate": 1.0,
        "failure_count": 0,
    }

    assert by_key["cache"]["summary"] == (
        "80.0% hit rate over 30 read(s)"
    )
    assert by_key["cache"]["headline"] == {
        "total_reads": 30,
        "hit_rate": 0.8,
        "current_keys": 12,
    }

    assert by_key["worker"]["summary"] == (
        "2 worker(s), 3 queued, 1 active"
    )
    assert by_key["worker"]["headline"]["workers_online"] == 2
    assert by_key["worker"]["headline"]["queue_depth"] == 3
    assert by_key["worker"]["headline"]["active_tasks"] == 1
    assert by_key["worker"]["headline"]["reasons"] == []

    assert by_key["simulation"]["summary"] == (
        "100.0% completion over 4 run(s)"
    )
    assert by_key["simulation"]["headline"]["total_simulations"] == 4
    assert by_key["simulation"]["headline"]["completion_rate"] == 1.0
    assert by_key["simulation"]["headline"]["failed_count"] == 0
    assert by_key["simulation"]["headline"]["reasons"] == []


# ---------------------------------------------------------------------------
# Worker service derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("broker", "workers_online", "expected_status", "expected_detail"),
    [
        (
            {"status": "ok", "error": None},
            2,
            "ok",
            "2 worker(s) online",
        ),
        (
            {"status": "ok", "error": None},
            0,
            "degraded",
            "Broker reachable but no workers online",
        ),
        (
            {"status": "error", "error": "connection refused"},
            0,
            "error",
            "connection refused",
        ),
        (
            {"status": "unconfigured", "error": None},
            0,
            "unconfigured",
            "Celery broker unconfigured or unsupported",
        ),
    ],
)
def test_worker_service_row_derived_from_worker_digest(
    broker: dict[str, Any],
    workers_online: int,
    expected_status: str,
    expected_detail: str,
) -> None:
    digests = _digests(
        worker={
            "verdict": VERDICT_NO_DATA,
            "reasons": [],
            "broker": broker,
            "totals": {
                "workers_online": workers_online,
                "active_tasks": 0,
                "reserved_tasks": 0,
                "scheduled_tasks": 0,
                "queue_depth": 0,
            },
        }
    )

    payload = build_system_overview(**digests, services=_services())
    worker_service = next(
        row for row in payload["services"] if row["name"] == "worker"
    )

    assert worker_service["status"] == expected_status
    assert worker_service["detail"] == expected_detail


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


def test_system_overview_route_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    real_builder = system_health_module.build_system_overview

    def recording_builder(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return real_builder(**kwargs)

    monkeypatch.setattr(
        system_health_module,
        "build_system_overview",
        recording_builder,
    )
    monkeypatch.setattr(
        system_health_module.metrics,
        "snapshot",
        lambda: {},
    )
    monkeypatch.setattr(
        system_health_module,
        "slow_queries_snapshot",
        lambda limit=10: [],
    )
    monkeypatch.setattr(
        system_health_module.response_cache_module,
        "current_key_counts",
        lambda: ({}, False),
    )
    monkeypatch.setattr(
        system_health_module.worker_health_module,
        "collect_worker_snapshot",
        lambda inspect, broker_client: {
            "workers_online": 2,
            "workers": [],
            "queues": [],
            "broker": {
                "status": "ok",
                "scheme": "redis",
                "database": 0,
                "error": None,
            },
        },
    )
    monkeypatch.setattr(
        system_health_module.worker_health_module,
        "build_worker_health",
        lambda **kwargs: _digests()["worker"],
    )
    gauges_seen: dict[str, Any] = {}

    def recording_gauges(snapshot: dict[str, Any]) -> None:
        gauges_seen.update(snapshot)

    monkeypatch.setattr(
        system_health_module.worker_health_module,
        "record_worker_gauges",
        recording_gauges,
    )
    monkeypatch.setattr(
        system_health_module.simulation_health_module,
        "collect_simulation_snapshot",
        lambda db, window_days=7: _digests()["simulation"],
    )
    monkeypatch.setattr(
        system_health_module.simulation_health_module,
        "build_simulation_health",
        lambda **kwargs: _digests()["simulation"],
    )
    monkeypatch.setattr(
        system_health_module,
        "_db_status",
        lambda db: {"status": "ok", "latency_ms": 1.2},
    )
    monkeypatch.setattr(
        system_health_module,
        "_redis_status",
        lambda: {"status": "ok", "latency_ms": 0.8},
    )

    class _FakeControl:
        def inspect(self, timeout: float) -> object:
            return object()

    monkeypatch.setattr(
        system_health_module.celery_app,
        "control",
        _FakeControl(),
    )

    payload = system_health_module.system_overview(db=object())

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    assert captured["services"]["database"]["status"] == "ok"
    assert captured["services"]["redis"]["status"] == "ok"
    assert captured["request"]["total_requests"] == 0
    assert captured["simulation"]["verdict"] == VERDICT_HEALTHY
    assert gauges_seen["workers_online"] == 2
    assert gauges_seen["broker"]["status"] == "ok"
    assert isinstance(SystemOverviewOut(**payload), SystemOverviewOut)
