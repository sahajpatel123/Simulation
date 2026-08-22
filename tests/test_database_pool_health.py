"""Tests for the database connection-pool health digest.

Covers the pure builder in ``app.core.database_pool_health`` (verdicts,
reasons, summaries), the live collectors with a real SQLAlchemy
QueuePool and fake server rows, the Prometheus gauge mirror, the route
contract, and the pool subsystem's integration into /system/overview.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy import pool as sqla_pool

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.core.database_pool_health import (  # noqa: E402
    POOL_STATUS_ERROR,
    POOL_STATUS_OK,
    POOL_STATUS_UNAVAILABLE,
    POOL_WATCH_UTILIZATION,
    REASON_POOL_NEARLY_EXHAUSTED,
    REASON_POOL_PROBE_ERROR,
    REASON_POOL_UTILIZATION_HIGH,
    REASON_SERVER_CONNECTIONS_HIGH,
    REASON_SERVER_NEARLY_EXHAUSTED,
    REASON_SERVER_PROBE_ERROR,
    SERVER_STATUS_ERROR,
    SERVER_STATUS_OK,
    SERVER_STATUS_UNAVAILABLE,
    VERDICT_DEGRADED,
    VERDICT_ERROR,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
    build_database_pool_health,
    collect_pool_snapshot,
    collect_server_snapshot,
    record_pool_gauges,
)
from app.core.metrics import metrics  # noqa: E402
from app.core.system_overview import build_system_overview  # noqa: E402
from app.schemas.system_health import DatabasePoolHealthOut  # noqa: E402


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Each test starts from an empty metrics registry."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    yield


def _pool_section(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": POOL_STATUS_OK,
        "pool_class": "QueuePool",
        "pool_size": 10,
        "max_overflow": 20,
        "checkedout": 6,
        "checkedin": 24,
        "overflow": 0,
        "total_capacity": 30,
        "utilization": 0.2,
        "pool_timeout_seconds": 30,
        "pool_recycle_seconds": 1800,
        "pre_ping": True,
        "error": None,
    }
    data.update(overrides)
    return data


def _server_section(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": SERVER_STATUS_OK,
        "reason": None,
        "active_connections": 24,
        "max_connections": 100,
        "connection_ratio": 0.24,
        "latency_ms": 1.5,
        "error": None,
    }
    data.update(overrides)
    return data


def _gauge(name: str) -> float | None:
    for (metric_name, _labels), value in metrics.snapshot()["gauges"].items():
        if metric_name == name:
            return float(value)
    return None


# ---------------------------------------------------------------------------
# Pure builder verdicts
# ---------------------------------------------------------------------------


def test_build_healthy_verdict_and_schema() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(),
        server=_server_section(),
        generated_at="now",
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["reasons"] == []
    assert payload["summary"] == (
        "6/30 pool connections in use, server 24/100"
    )
    model = DatabasePoolHealthOut(**payload)
    assert model.verdict == VERDICT_HEALTHY
    assert model.pool.checkedout == 6
    assert model.pool.utilization == pytest.approx(0.2)
    assert model.server.connection_ratio == pytest.approx(0.24)


def test_build_watch_on_high_pool_utilization() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(utilization=0.87, checkedout=26),
        server=_server_section(),
    )

    assert payload["verdict"] == VERDICT_WATCH
    assert REASON_POOL_UTILIZATION_HIGH in payload["reasons"]


def test_build_watch_at_pool_threshold() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(utilization=POOL_WATCH_UTILIZATION),
        server=_server_section(),
    )

    assert payload["verdict"] == VERDICT_WATCH
    assert REASON_POOL_UTILIZATION_HIGH in payload["reasons"]


def test_build_degraded_on_nearly_exhausted_pool() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(utilization=0.97, checkedout=29),
        server=_server_section(),
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert REASON_POOL_NEARLY_EXHAUSTED in payload["reasons"]


def test_build_watch_on_high_server_connection_ratio() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(),
        server=_server_section(
            active_connections=85,
            connection_ratio=0.85,
        ),
    )

    assert payload["verdict"] == VERDICT_WATCH
    assert REASON_SERVER_CONNECTIONS_HIGH in payload["reasons"]


def test_build_degraded_on_nearly_exhausted_server() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(),
        server=_server_section(
            active_connections=97,
            connection_ratio=0.97,
        ),
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert REASON_SERVER_NEARLY_EXHAUSTED in payload["reasons"]


def test_build_no_data_when_both_sections_unavailable() -> None:
    payload = build_database_pool_health(
        pool={"status": POOL_STATUS_UNAVAILABLE},
        server={"status": SERVER_STATUS_UNAVAILABLE},
    )

    assert payload["verdict"] == VERDICT_NO_DATA
    assert payload["reasons"] == []
    assert payload["summary"] == "Database pool unavailable"


def test_build_error_on_pool_probe_error() -> None:
    payload = build_database_pool_health(
        pool={"status": POOL_STATUS_ERROR, "error": "boom"},
        server=_server_section(),
    )

    assert payload["verdict"] == VERDICT_ERROR
    assert REASON_POOL_PROBE_ERROR in payload["reasons"]


def test_build_error_on_server_probe_error() -> None:
    payload = build_database_pool_health(
        pool=_pool_section(utilization=0.97),
        server={"status": SERVER_STATUS_ERROR, "error": "boom"},
    )

    assert payload["verdict"] == VERDICT_ERROR
    assert REASON_SERVER_PROBE_ERROR in payload["reasons"]


def test_build_server_only_signal_when_pool_unavailable() -> None:
    payload = build_database_pool_health(
        pool={"status": POOL_STATUS_UNAVAILABLE},
        server=_server_section(connection_ratio=0.6),
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["summary"] == "server 24/100 connections"


# ---------------------------------------------------------------------------
# Pool collector
# ---------------------------------------------------------------------------


def test_collect_pool_snapshot_reads_queue_pool() -> None:
    engine = create_engine(
        "sqlite://",
        poolclass=sqla_pool.QueuePool,
        pool_size=3,
        max_overflow=5,
        pool_timeout=7,
        pool_recycle=1800,
    )
    connections = [engine.connect() for _ in range(5)]
    try:
        snapshot = collect_pool_snapshot(engine)
    finally:
        for connection in connections:
            connection.close()

    assert snapshot["status"] == POOL_STATUS_OK
    assert snapshot["pool_class"] == "QueuePool"
    assert snapshot["pool_size"] == 3
    assert snapshot["max_overflow"] == 5
    assert snapshot["checkedout"] == 5
    assert snapshot["checkedin"] == 0
    assert snapshot["overflow"] == 2
    assert snapshot["total_capacity"] == 8
    assert snapshot["utilization"] == pytest.approx(0.625)
    assert snapshot["pool_timeout_seconds"] == 7
    assert snapshot["pool_recycle_seconds"] == 1800
    assert snapshot["pre_ping"] is False


def test_collect_pool_snapshot_unavailable_without_pool() -> None:
    snapshot = collect_pool_snapshot(object())

    assert snapshot["status"] == POOL_STATUS_UNAVAILABLE
    assert snapshot["error"]


def test_collect_pool_snapshot_error_on_broken_pool() -> None:
    class _BrokenPool:
        def checkedout(self) -> int:
            raise RuntimeError("pool exploded")

    class _BrokenEngine:
        pool = _BrokenPool()

    snapshot = collect_pool_snapshot(_BrokenEngine())

    assert snapshot["status"] == POOL_STATUS_ERROR
    # Client-facing error carries the exception class only — the raw
    # message must never leak through a health digest.
    assert snapshot.get("error") == "RuntimeError"
    assert "pool exploded" not in (snapshot.get("error") or "")


# ---------------------------------------------------------------------------
# Server collector
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping


class _FakeResult:
    def __init__(self, row: _FakeRow | None = None) -> None:
        self._row = row

    def fetchone(self) -> _FakeRow | None:
        return self._row


class _FakeDB:
    def __init__(
        self,
        row: _FakeRow | None = None,
        error: Exception | None = None,
    ) -> None:
        self._row = row
        self._error = error
        self.executed = False

    def execute(self, stmt: Any) -> _FakeResult:
        self.executed = True
        if self._error is not None:
            raise self._error
        return _FakeResult(self._row)


def test_collect_server_snapshot_skips_non_postgresql() -> None:
    db = _FakeDB()

    snapshot = collect_server_snapshot(db, "sqlite:///local.db")

    assert snapshot["status"] == SERVER_STATUS_UNAVAILABLE
    assert snapshot["reason"] == "non_postgresql"
    assert snapshot["connection_ratio"] is None
    assert db.executed is False


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://app:secret@db:5432/thecee",
        "postgres://app:secret@db:5432/thecee",
        "postgresql+psycopg://app:secret@db:5432/thecee",
        "postgres+psycopg2://app:secret@db:5432/thecee",
        "POSTGRESQL://app:secret@db:5432/thecee",
    ],
)
def test_collect_server_snapshot_recognizes_postgresql_url_aliases(
    database_url: str,
) -> None:
    row = _FakeRow(
        {"active_connections": 12, "max_connections": 100}
    )
    db = _FakeDB(row=row)

    snapshot = collect_server_snapshot(db, database_url)

    assert snapshot["status"] == SERVER_STATUS_OK
    assert snapshot["active_connections"] == 12
    assert db.executed is True


def test_collect_server_snapshot_reads_rows() -> None:
    row = _FakeRow(
        {"active_connections": 12, "max_connections": 100}
    )
    db = _FakeDB(row=row)

    snapshot = collect_server_snapshot(db, "postgresql://app")

    assert snapshot["status"] == SERVER_STATUS_OK
    assert snapshot["active_connections"] == 12
    assert snapshot["max_connections"] == 100
    assert snapshot["connection_ratio"] == pytest.approx(0.12)
    assert isinstance(snapshot["latency_ms"], float)
    assert snapshot["latency_ms"] >= 0.0
    assert db.executed is True


def test_collect_server_snapshot_handles_empty_result() -> None:
    db = _FakeDB(row=None)

    snapshot = collect_server_snapshot(db, "postgresql://app")

    assert snapshot["status"] == SERVER_STATUS_ERROR
    assert snapshot["reason"] == "empty_probe_result"
    assert snapshot["connection_ratio"] is None


def test_collect_server_snapshot_error_on_db_failure() -> None:
    db = _FakeDB(error=RuntimeError("connection refused"))

    snapshot = collect_server_snapshot(db, "postgresql://app")

    assert snapshot["status"] == SERVER_STATUS_ERROR
    assert snapshot["reason"] == "probe_exception"
    assert snapshot["connection_ratio"] is None
    # Client-facing error carries the exception class only — the raw
    # message (which can embed host names / SQL fragments) must not leak.
    assert snapshot.get("error") == "RuntimeError"
    assert "connection refused" not in (snapshot.get("error") or "")


# ---------------------------------------------------------------------------
# Prometheus gauge mirror
# ---------------------------------------------------------------------------


def test_record_pool_gauges_mirrors_snapshot() -> None:
    record_pool_gauges(
        _pool_section(
            checkedout=7,
            checkedin=23,
            overflow=2,
            utilization=0.233,
        ),
        _server_section(
            active_connections=31,
            max_connections=100,
            connection_ratio=0.31,
        ),
    )

    assert _gauge("thecee_db_pool_checked_out") == 7
    assert _gauge("thecee_db_pool_checked_in") == 23
    assert _gauge("thecee_db_pool_overflow") == 2
    assert _gauge("thecee_db_pool_utilization") == pytest.approx(0.233)
    assert _gauge("thecee_db_server_connections") == 31
    assert _gauge("thecee_db_server_max_connections") == 100
    assert _gauge("thecee_db_server_connection_ratio") == pytest.approx(0.31)


def test_record_pool_gauges_skips_absent_probes() -> None:
    record_pool_gauges(
        {"status": POOL_STATUS_UNAVAILABLE},
        {"status": SERVER_STATUS_UNAVAILABLE},
    )

    # Absent probes must never masquerade as zero connections.
    assert _gauge("thecee_db_pool_checked_out") is None
    assert _gauge("thecee_db_server_connections") is None
    assert _gauge("thecee_db_server_max_connections") is None


# ---------------------------------------------------------------------------
# Route contract + overview integration
# ---------------------------------------------------------------------------


def test_database_pool_health_route_uses_typed_response() -> None:
    from app.api.v1 import system_health as system_health_module

    matching = [
        route
        for route in system_health_module.router.routes
        if isinstance(route, APIRoute)
        and route.path.endswith("/database-pool-health")
    ]

    assert matching
    assert matching[0].response_model is DatabasePoolHealthOut


def test_database_pool_health_route_composes_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import system_health as system_health_module

    monkeypatch.setattr(
        system_health_module.database_pool_health_module,
        "collect_pool_snapshot",
        lambda engine: _pool_section(),
    )
    monkeypatch.setattr(
        system_health_module.database_pool_health_module,
        "collect_server_snapshot",
        lambda db, database_url: _server_section(),
    )
    monkeypatch.setattr(
        system_health_module.database_pool_health_module,
        "record_pool_gauges",
        lambda pool, server: None,
    )

    payload = system_health_module.database_pool_health(db=object())

    assert payload["verdict"] == VERDICT_HEALTHY
    assert DatabasePoolHealthOut(**payload).verdict == VERDICT_HEALTHY


def _healthy_digests() -> dict[str, Any]:
    return {
        "request": {
            "total_requests": 1,
            "overall_error_rate": 0.0,
            "route_count": 1,
        },
        "query": {
            "total_queries": 1,
            "error_rate": 0.0,
            "slow_query_count": 0,
            "verdict": VERDICT_HEALTHY,
        },
        "llm": {
            "total_attempts": 1,
            "success_rate": 1.0,
            "failure_count": 0,
            "verdict": VERDICT_HEALTHY,
        },
        "cache": {
            "total_reads": 1,
            "hit_rate": 1.0,
            "current_keys": 1,
            "verdict": VERDICT_HEALTHY,
        },
        "worker": {
            "verdict": VERDICT_HEALTHY,
            "reasons": [],
            "broker": {"status": "ok", "error": None},
            "totals": {
                "workers_online": 1,
                "active_tasks": 0,
                "reserved_tasks": 0,
                "scheduled_tasks": 0,
                "queue_depth": 0,
            },
        },
        "simulation": {
            "verdict": VERDICT_HEALTHY,
            "reasons": [],
            "total_simulations": 1,
            "completion_rate": 1.0,
            "failed_count": 0,
        },
    }


def test_overview_pool_watch_marks_overall_degraded() -> None:
    pool_digest = build_database_pool_health(
        pool=_pool_section(utilization=0.87, checkedout=26),
        server=_server_section(),
    )

    payload = build_system_overview(
        **_healthy_digests(),
        pool=pool_digest,
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "ok", "latency_ms": 0.8, "error": None},
        },
    )

    assert payload["status"] == "degraded"
    assert payload["healthy"] is False
    assert "pool" in payload["unhealthy_components"]
    pool_row = next(
        row for row in payload["subsystems"] if row["key"] == "pool"
    )
    assert pool_row["verdict"] == VERDICT_WATCH
    assert pool_row["healthy"] is False
    assert pool_row["headline"]["checkedout"] == 26
    assert pool_row["headline"]["total_capacity"] == 30


def test_overview_pool_no_data_counts_as_healthy() -> None:
    pool_digest = build_database_pool_health(
        pool={"status": POOL_STATUS_UNAVAILABLE},
        server={"status": SERVER_STATUS_UNAVAILABLE},
    )

    payload = build_system_overview(
        **_healthy_digests(),
        pool=pool_digest,
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "ok", "latency_ms": 0.8, "error": None},
        },
    )

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    pool_row = next(
        row for row in payload["subsystems"] if row["key"] == "pool"
    )
    assert pool_row["verdict"] == VERDICT_NO_DATA
    assert pool_row["healthy"] is True
