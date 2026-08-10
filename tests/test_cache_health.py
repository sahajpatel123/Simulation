"""Unit tests for response-cache observability.

Covers the counter recording in ``app.core.response_cache`` and the pure
digest builder in ``app.core.cache_health``. These run without a live Redis
or FastAPI app, so they are safe to execute anywhere.
"""

from __future__ import annotations

import sys
import types

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

import app.api.v1.system_health as system_health_module
from app.core import response_cache
from app.core.cache_health import build_cache_health
from app.core.metrics import (
    CACHE_INVALIDATION_COUNTER,
    CACHE_READ_COUNTER,
    CACHE_WRITE_COUNTER,
    _Metrics,
)
from app.schemas.system_health import CacheHealthOut


class _FakeRedis:
    """Minimal Redis stand-in with knobs for get/scan failures."""

    def __init__(
        self,
        store: dict[str, str] | None = None,
        *,
        raise_on_get: bool = False,
        raise_on_scan: bool = False,
        raise_on_setex: bool = False,
    ) -> None:
        self.store = dict(store or {})
        self.raise_on_get = raise_on_get
        self.raise_on_scan = raise_on_scan
        self.raise_on_setex = raise_on_setex

    def get(self, key: str) -> str | None:
        if self.raise_on_get:
            raise RuntimeError("get boom")
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        if self.raise_on_setex:
            raise RuntimeError("setex boom")
        self.store[key] = value

    def scan_iter(self, match: str | None = None, count: int = 100):
        if self.raise_on_scan:
            raise RuntimeError("scan boom")
        return iter(self.store)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


def _counter_value(
    snapshot: dict[str, object],
    name: str,
    labels: dict[str, str],
) -> int:
    counters = snapshot.get("counters") or {}
    key = (name, tuple(sorted(labels.items())))
    return int(counters.get(key, 0))


def test_cache_health_builder_reports_hit_miss_and_rates():
    metrics = _Metrics()
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "project-health", "result": "hit"},
    )
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "project-health", "result": "hit"},
    )
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "project-health", "result": "miss"},
    )
    metrics.inc_counter(
        CACHE_WRITE_COUNTER,
        {"namespace": "project-health", "result": "success"},
    )
    metrics.inc_counter(
        CACHE_INVALIDATION_COUNTER,
        {
            "namespace": "project-health",
            "scope": "user",
            "result": "success",
        },
    )

    payload = build_cache_health(
        metrics.snapshot(),
        key_counts={"project-health": 4},
        redis_configured=True,
    )

    assert payload["verdict"] == "HEALTHY"
    assert payload["redis_configured"] is True
    assert payload["total_reads"] == 3
    assert payload["total_hits"] == 2
    assert payload["total_misses"] == 1
    assert payload["hit_rate"] == round(2 / 3, 6)
    assert payload["total_writes"] == 1
    assert payload["total_invalidations"] == 1
    assert payload["current_keys"] == 4

    row = payload["namespaces"][0]
    assert row["namespace"] == "project-health"
    assert row["hits"] == 2
    assert row["misses"] == 1
    assert row["writes"] == 1
    assert row["invalidations"] == 1
    assert row["current_keys"] == 4


def test_cache_health_builder_handles_unconfigured_and_empty():
    unconfigured = build_cache_health(
        {},
        redis_configured=False,
    )
    assert unconfigured["verdict"] == "UNCONFIGURED"
    assert unconfigured["namespaces"] == []

    no_data = build_cache_health(
        {},
        redis_configured=True,
    )
    assert no_data["verdict"] == "NO_DATA"
    assert no_data["hit_rate"] is None


def test_cache_health_builder_watches_when_only_unconfigured_operations():
    metrics = _Metrics()
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "unconfigured"},
    )

    payload = build_cache_health(
        metrics.snapshot(),
        redis_configured=True,
    )

    assert payload["verdict"] == "WATCH"
    assert payload["total_reads"] == 1
    assert payload["hit_rate"] is None


def test_cache_health_builder_degrades_on_read_errors():
    metrics = _Metrics()
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "hit"},
    )
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "error"},
    )

    payload = build_cache_health(
        metrics.snapshot(),
        redis_configured=True,
    )

    assert payload["verdict"] == "DEGRADED"
    assert payload["read_error_rate"] == 0.5


def test_cache_health_builder_watches_on_unconfigured_operations():
    metrics = _Metrics()
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "hit"},
    )
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "unconfigured"},
    )

    payload = build_cache_health(
        metrics.snapshot(),
        redis_configured=True,
    )

    assert payload["verdict"] == "WATCH"
    assert payload["hit_rate"] == 1.0
    assert payload["unconfigured_read_count"] == 1


def test_response_cache_records_hit_miss_write_and_invalidation(
    monkeypatch,
):
    fresh_metrics = _Metrics()
    monkeypatch.setattr(response_cache, "metrics", fresh_metrics)
    client = _FakeRedis()
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: client,
    )

    response_cache.cache_set_json(
        "project-health",
        {"id": 3},
        7,
        {"ok": True},
    )
    assert response_cache.cache_get_json(
        "project-health", {"id": 3}, 7
    ) == {"ok": True}
    assert response_cache.cache_get_json(
        "project-health", {"id": 9}, 7
    ) is None
    removed = response_cache.cache_invalidate(
        "project-health", user_id=7
    )
    assert removed == 1

    snapshot = fresh_metrics.snapshot()
    assert _counter_value(
        snapshot,
        CACHE_READ_COUNTER,
        {"namespace": "project-health", "result": "hit"},
    ) == 1
    assert _counter_value(
        snapshot,
        CACHE_READ_COUNTER,
        {"namespace": "project-health", "result": "miss"},
    ) == 1
    assert _counter_value(
        snapshot,
        CACHE_WRITE_COUNTER,
        {"namespace": "project-health", "result": "success"},
    ) == 1
    assert _counter_value(
        snapshot,
        CACHE_INVALIDATION_COUNTER,
        {
            "namespace": "project-health",
            "scope": "user",
            "result": "success",
        },
    ) == 1


def test_response_cache_records_read_errors(monkeypatch):
    fresh_metrics = _Metrics()
    monkeypatch.setattr(response_cache, "metrics", fresh_metrics)
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: _FakeRedis(raise_on_get=True),
    )

    assert response_cache.cache_get_json("ns", {"id": 1}, 1) is None

    snapshot = fresh_metrics.snapshot()
    assert _counter_value(
        snapshot,
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "error"},
    ) == 1


def test_response_cache_records_corrupt_payload_as_read_error(monkeypatch):
    fresh_metrics = _Metrics()
    monkeypatch.setattr(response_cache, "metrics", fresh_metrics)
    client = _FakeRedis()
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: client,
    )
    response_cache.cache_set_json(
        "ns", {"id": 1}, 1, {"ok": True}
    )
    client.store[next(iter(client.store))] = "not-json"

    assert response_cache.cache_get_json("ns", {"id": 1}, 1) is None

    snapshot = fresh_metrics.snapshot()
    assert _counter_value(
        snapshot,
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "error"},
    ) == 1
    assert _counter_value(
        snapshot,
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "hit"},
    ) == 0


def test_response_cache_records_write_errors(monkeypatch):
    fresh_metrics = _Metrics()
    monkeypatch.setattr(response_cache, "metrics", fresh_metrics)
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: _FakeRedis(raise_on_setex=True),
    )

    response_cache.cache_set_json(
        "ns", {"id": 1}, 1, {"ok": True}
    )

    snapshot = fresh_metrics.snapshot()
    assert _counter_value(
        snapshot,
        CACHE_WRITE_COUNTER,
        {"namespace": "ns", "result": "error"},
    ) == 1
    assert _counter_value(
        snapshot,
        CACHE_WRITE_COUNTER,
        {"namespace": "ns", "result": "success"},
    ) == 0


def test_response_cache_records_invalidation_errors(monkeypatch):
    fresh_metrics = _Metrics()
    monkeypatch.setattr(response_cache, "metrics", fresh_metrics)
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: _FakeRedis(raise_on_scan=True),
    )

    assert response_cache.cache_invalidate("ns") == 0

    snapshot = fresh_metrics.snapshot()
    assert _counter_value(
        snapshot,
        CACHE_INVALIDATION_COUNTER,
        {
            "namespace": "ns",
            "scope": "all",
            "result": "error",
        },
    ) == 1


def test_current_key_counts_returns_none_when_scan_fails(monkeypatch):
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: _FakeRedis(raise_on_scan=True),
    )

    counts, configured = response_cache.current_key_counts()

    assert counts is None
    assert configured is True


def test_current_key_counts_groups_by_namespace(monkeypatch):
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: None,
    )
    assert response_cache.current_key_counts() == (None, False)

    client = _FakeRedis(
        {
            "rcache:project-health:7:a": "{}",
            "rcache:project-health:7:b": "{}",
            "rcache:user-stats:1:c": "{}",
        }
    )
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: client,
    )

    counts, configured = response_cache.current_key_counts()

    assert configured is True
    assert counts == {
        "project-health": 2,
        "user-stats": 1,
    }


def test_cache_health_builder_sanitizes_key_counts():
    metrics = _Metrics()
    metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "hit"},
    )

    payload = build_cache_health(
        metrics.snapshot(),
        key_counts={
            "ns": -3,
            "other": "12",
            "bad": None,
            "flag": True,
        },
        redis_configured=True,
    )

    assert payload["current_keys"] == 12
    row = payload["namespaces"][0]
    assert row["current_keys"] == 0
    CacheHealthOut(**payload)


def test_cache_health_builder_verdict_thresholds():
    def payload_with_read_errors(errors: int, hits: int) -> dict:
        metrics = _Metrics()
        for _ in range(errors):
            metrics.inc_counter(
                CACHE_READ_COUNTER,
                {"namespace": "ns", "result": "error"},
            )
        for _ in range(hits):
            metrics.inc_counter(
                CACHE_READ_COUNTER,
                {"namespace": "ns", "result": "hit"},
            )
        return build_cache_health(
            metrics.snapshot(),
            redis_configured=True,
        )

    # 1/101 ≈ 0.99% — under the WATCH band.
    assert payload_with_read_errors(errors=1, hits=100)["verdict"] == (
        "HEALTHY"
    )
    # 1/99 ≈ 1.01% — crosses the WATCH band.
    assert payload_with_read_errors(errors=1, hits=98)["verdict"] == (
        "WATCH"
    )
    # 1/20 == 5% exactly — WATCH, not yet DEGRADED.
    assert payload_with_read_errors(errors=1, hits=19)["verdict"] == (
        "WATCH"
    )
    # 1/19 ≈ 5.26% — crosses the DEGRADED band.
    assert payload_with_read_errors(errors=1, hits=18)["verdict"] == (
        "DEGRADED"
    )


def test_cache_health_route_returns_schema_valid_payload(monkeypatch):
    fresh_metrics = _Metrics()
    fresh_metrics.inc_counter(
        CACHE_READ_COUNTER,
        {"namespace": "ns", "result": "hit"},
    )
    monkeypatch.setattr(system_health_module, "metrics", fresh_metrics)
    monkeypatch.setattr(
        response_cache.redis_client,
        "get_redis_client",
        lambda: None,
    )

    payload = system_health_module.cache_health()

    assert CacheHealthOut(**payload)
    assert payload["verdict"] == "UNCONFIGURED"
    assert payload["total_reads"] == 1
