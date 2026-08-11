"""Tests for the live-progress WebSocket delivery health digest.

Covers the pure builder in ``app.core.websocket_health`` (verdict matrix,
delivery modes, reasons/narrative), the route contract with fake Redis
clients and bridge/listener state, and the subsystem's integration into
``/system/overview``. No live Redis, WebSocket or Celery is required.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi.routing import APIRoute

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.core.metrics import metrics  # noqa: E402
from app.core.system_overview import build_system_overview  # noqa: E402
from app.core.websocket_health import (  # noqa: E402
    MODE_IN_PROCESS_FALLBACK,
    MODE_REDIS_CROSS_PROCESS,
    MODE_REDIS_STANDBY,
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_UNCONFIGURED,
    VERDICT_WATCH,
    build_websocket_health,
    record_websocket_gauges,
)
from app.schemas.system_health import WebsocketHealthOut  # noqa: E402


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Each test starts from an empty metrics registry."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    yield


def _gauge(name: str) -> float | None:
    for (metric_name, _labels), value in metrics.snapshot()["gauges"].items():
        if metric_name == name:
            return float(value)
    return None


# ---------------------------------------------------------------------------
# Pure builder: verdict matrix
# ---------------------------------------------------------------------------


def test_unconfigured_redis_is_healthy_fallback() -> None:
    payload = build_websocket_health(
        redis_configured=False,
        bridge_running=False,
    )

    assert payload["verdict"] == VERDICT_UNCONFIGURED
    assert payload["healthy"] is True
    assert payload["delivery_mode"] == MODE_IN_PROCESS_FALLBACK
    assert payload["reasons"]
    assert "API process" in payload["narrative"]
    assert WebsocketHealthOut(**payload).healthy is True


def test_healthy_redis_relay_with_listeners() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=2,
        connected_simulation_ids=[7, 8],
        channel="thecee:simulation-progress",
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["healthy"] is True
    assert payload["delivery_mode"] == MODE_REDIS_CROSS_PROCESS
    assert payload["connection_count"] == 2
    assert payload["connected_simulation_ids"] == [7, 8]
    assert payload["reasons"] == []
    assert "2 live listener(s)" in payload["narrative"]


def test_bridge_not_running_with_listeners_is_degraded() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=False,
        connection_count=1,
        connected_simulation_ids=[42],
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["healthy"] is False
    assert payload["delivery_mode"] == MODE_REDIS_STANDBY
    assert any("Subscriber is not running" in reason for reason in payload["reasons"])


def test_bridge_not_running_without_listeners_is_healthy_standby() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=False,
        connection_count=0,
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["healthy"] is True
    assert payload["delivery_mode"] == MODE_REDIS_STANDBY
    assert payload["connection_count"] == 0
    assert "standby" in payload["narrative"]


def test_redis_unreachable_is_degraded() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=False,
        bridge_running=True,
        connection_count=1,
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["healthy"] is False
    assert any("unreachable" in reason for reason in payload["reasons"])


def test_active_publish_outage_is_degraded() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=1,
        last_publish_failure_age_seconds=5.0,
    )

    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["healthy"] is False
    assert any("5s ago" in reason for reason in payload["reasons"])


def test_recovered_publish_outage_is_watch() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=1,
        last_publish_failure_age_seconds=120.0,
    )

    assert payload["verdict"] == VERDICT_WATCH
    assert payload["healthy"] is False


def test_aged_out_publish_outage_is_healthy() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=1,
        last_publish_failure_age_seconds=600.0,
    )

    assert payload["verdict"] == VERDICT_HEALTHY
    assert payload["healthy"] is True


def test_builder_defensively_sanitises_inputs() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count="3",
        connected_simulation_ids=[0, -5, 9, "11"],
        last_publish_failure_age_seconds=-1,
    )

    assert payload["connection_count"] == 3
    assert payload["connected_simulation_ids"] == [9, 11]
    assert payload["last_publish_failure_age_seconds"] is None


# ---------------------------------------------------------------------------
# Prometheus gauge mirror
# ---------------------------------------------------------------------------


def test_record_gauges_healthy_digest() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=2,
        connected_simulation_ids=[7, 8],
    )

    record_websocket_gauges(payload)

    assert _gauge("thecee_websocket_connections") == 2.0
    assert _gauge("thecee_websocket_bridge_running") == 1.0
    assert _gauge("thecee_websocket_redis_configured") == 1.0
    assert _gauge("thecee_websocket_redis_reachable") == 1.0
    assert _gauge("thecee_websocket_unhealthy") == 0.0
    assert _gauge("thecee_websocket_last_publish_failure_age_seconds") is None


def test_record_gauges_degraded_digest() -> None:
    payload = build_websocket_health(
        redis_configured=True,
        redis_reachable=False,
        bridge_running=True,
        connection_count=1,
        last_publish_failure_age_seconds=4.0,
    )

    record_websocket_gauges(payload)

    assert _gauge("thecee_websocket_redis_reachable") == 0.0
    assert _gauge("thecee_websocket_unhealthy") == 1.0
    assert (
        _gauge("thecee_websocket_last_publish_failure_age_seconds") == 4.0
    )


def test_record_gauges_unconfigured_leaves_absences_unset() -> None:
    payload = build_websocket_health(
        redis_configured=False,
        bridge_running=False,
        connection_count=0,
    )

    record_websocket_gauges(payload)

    assert _gauge("thecee_websocket_connections") == 0.0
    assert _gauge("thecee_websocket_bridge_running") == 0.0
    assert _gauge("thecee_websocket_redis_configured") == 0.0
    assert _gauge("thecee_websocket_unhealthy") == 0.0
    assert _gauge("thecee_websocket_redis_reachable") is None
    assert _gauge("thecee_websocket_last_publish_failure_age_seconds") is None


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


class _FakeRedisOk:
    def ping(self) -> bool:
        return True


class _FakeRedisDown:
    def ping(self) -> bool:
        raise ConnectionError("redis down")


def test_websocket_health_route_uses_typed_response() -> None:
    from app.api.v1 import system_health as system_health_module

    matching = [
        route
        for route in system_health_module.router.routes
        if isinstance(route, APIRoute)
        and route.path.endswith("/websocket-health")
    ]

    assert matching
    assert matching[0].response_model is WebsocketHealthOut


def test_websocket_health_route_composes_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import system_health as system_health_module

    monkeypatch.setattr(
        system_health_module, "get_redis_client", lambda: _FakeRedisOk()
    )
    monkeypatch.setattr(
        system_health_module.progress_bridge,
        "is_running",
        lambda: True,
    )
    monkeypatch.setattr(
        system_health_module.ws_manager,
        "_connections",
        {7: object(), 8: object()},
    )

    payload = system_health_module.websocket_health()

    assert payload.verdict == VERDICT_HEALTHY
    assert payload.delivery_mode == MODE_REDIS_CROSS_PROCESS
    assert payload.connection_count == 2
    assert payload.connected_simulation_ids == [7, 8]
    assert payload.channel == "thecee:simulation-progress"
    # The route mirrors digest state into Prometheus gauges.
    assert _gauge("thecee_websocket_connections") == 2.0
    assert _gauge("thecee_websocket_bridge_running") == 1.0
    assert _gauge("thecee_websocket_unhealthy") == 0.0


def test_websocket_health_route_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import system_health as system_health_module

    monkeypatch.setattr(system_health_module, "get_redis_client", lambda: None)
    monkeypatch.setattr(
        system_health_module.progress_bridge,
        "is_running",
        lambda: False,
    )
    monkeypatch.setattr(
        system_health_module.ws_manager,
        "_connections",
        {},
    )

    payload = system_health_module.websocket_health()

    assert payload.verdict == VERDICT_UNCONFIGURED
    assert payload.healthy is True
    assert payload.delivery_mode == MODE_IN_PROCESS_FALLBACK


def test_websocket_health_route_redis_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import system_health as system_health_module

    monkeypatch.setattr(
        system_health_module, "get_redis_client", lambda: _FakeRedisDown()
    )
    monkeypatch.setattr(
        system_health_module.progress_bridge,
        "is_running",
        lambda: True,
    )
    monkeypatch.setattr(
        system_health_module.ws_manager,
        "_connections",
        {7: object()},
    )

    payload = system_health_module.websocket_health()

    assert payload.verdict == VERDICT_DEGRADED
    assert payload.healthy is False
    assert payload.redis_reachable is False


# ---------------------------------------------------------------------------
# Overview integration
# ---------------------------------------------------------------------------


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
        "pool": {
            "verdict": VERDICT_HEALTHY,
            "reasons": [],
            "pool": {
                "status": "ok",
                "checkedout": 1,
                "total_capacity": 30,
                "utilization": 0.03,
            },
            "server": {
                "status": "ok",
                "active_connections": 3,
                "max_connections": 100,
                "connection_ratio": 0.03,
            },
        },
    }


def test_overview_websocket_healthy_counts_as_ok() -> None:
    websocket_digest = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=2,
        connected_simulation_ids=[1, 2],
    )

    payload = build_system_overview(
        **_healthy_digests(),
        websocket=websocket_digest,
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "ok", "latency_ms": 0.8, "error": None},
        },
    )

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    row = next(
        row for row in payload["subsystems"] if row["key"] == "websocket"
    )
    assert row["label"] == "Live progress delivery"
    assert row["verdict"] == VERDICT_HEALTHY
    assert row["healthy"] is True
    assert row["headline"]["connection_count"] == 2


def test_overview_websocket_watch_marks_overall_degraded() -> None:
    websocket_digest = build_websocket_health(
        redis_configured=True,
        redis_reachable=True,
        bridge_running=True,
        connection_count=1,
        last_publish_failure_age_seconds=120.0,
    )

    payload = build_system_overview(
        **_healthy_digests(),
        websocket=websocket_digest,
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "ok", "latency_ms": 0.8, "error": None},
        },
    )

    assert payload["status"] == "degraded"
    assert payload["healthy"] is False
    assert "websocket" in payload["unhealthy_components"]


def test_overview_websocket_unconfigured_counts_as_healthy() -> None:
    websocket_digest = build_websocket_health(
        redis_configured=False,
        bridge_running=False,
    )

    payload = build_system_overview(
        **_healthy_digests(),
        websocket=websocket_digest,
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "unconfigured", "latency_ms": None, "error": None},
        },
    )

    assert payload["status"] == "ok"
    assert payload["healthy"] is True
    row = next(
        row for row in payload["subsystems"] if row["key"] == "websocket"
    )
    assert row["verdict"] == VERDICT_UNCONFIGURED
    assert row["healthy"] is True


def test_overview_websocket_omitted_defaults_to_unconfigured() -> None:
    payload = build_system_overview(
        **_healthy_digests(),
        services={
            "database": {"status": "ok", "latency_ms": 1.2, "error": None},
            "redis": {"status": "unconfigured", "latency_ms": None, "error": None},
        },
    )

    row = next(
        row for row in payload["subsystems"] if row["key"] == "websocket"
    )
    assert row["verdict"] == VERDICT_UNCONFIGURED
    assert row["healthy"] is True
