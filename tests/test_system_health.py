"""Tests for the /system/health summary endpoint."""
from __future__ import annotations

import sys
import types

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.api.v1.system_health import build_health_summary, system_health


def test_build_health_summary_healthy_when_all_ok() -> None:
    summary = build_health_summary(
        database={"status": "ok", "latency_ms": 1.2},
        redis={"status": "ok", "latency_ms": 0.8},
        worker={"worker_reachable": True, "workers_online": 1},
        checked_at="now",
    )

    assert summary["healthy"] is True
    assert summary["status"] == "ok"
    assert summary["checked_at"] == "now"


def test_build_health_summary_degraded_when_db_down() -> None:
    summary = build_health_summary(
        database={"status": "error", "error": "down"},
        redis={"status": "ok"},
        worker={"worker_reachable": False, "workers_online": 0},
    )

    assert summary["healthy"] is False
    assert summary["status"] == "degraded"


def test_build_health_summary_redis_unconfigured_counts_healthy() -> None:
    summary = build_health_summary(
        database={"status": "ok"},
        redis={"status": "unconfigured"},
        worker={"worker_reachable": False, "workers_online": 0},
    )

    assert summary["healthy"] is True


def test_system_health_route_returns_summary() -> None:
    from app.schemas.system_health import SystemHealthOut

    class _OkDB:
        def execute(self, stmt):
            return object()

    summary = system_health(db=_OkDB())

    assert "healthy" in summary
    assert "checks" in summary
    assert "database" in summary["checks"]
    assert isinstance(SystemHealthOut(**summary), SystemHealthOut)
