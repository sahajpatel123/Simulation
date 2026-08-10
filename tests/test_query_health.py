"""Tests for the DB query-health digest endpoint.

The digest is a pure read over the metrics registry filled by the
engine-level query listener (``app.core.query_metrics``). These tests pin
the totals, error-rate accounting, histogram percentile interpolation,
per-kind breakdown, slow-query sanitisation, verdict thresholds and the
route contract so the ops dashboard can rely on stable numbers.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.core.metrics import metrics
from app.core.query_health import (
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
    build_query_health,
)
from app.core.query_metrics import (
    KIND_INSERT,
    KIND_OTHER,
    KIND_SELECT,
    QUERY_COUNTER,
    QUERY_DURATION_HISTOGRAM,
    QUERY_ERROR_COUNTER,
    SLOW_QUERY_COUNTER,
)
from app.schemas.system_health import QueryHealthOut

# Importing ``app.api.v1.system_health`` pulls in the whole API router, which
# imports the billing router and the real ``razorpay`` SDK. On Python 3.12 the
# installed SDK fails on ``pkg_resources``; stub it the same way the other
# route tests do before any API-route import.
if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1 import system_health as system_health_module


def _counter_key(
    name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (name, tuple(sorted(labels.items())))


def _histogram_key(
    name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (name, tuple(sorted(labels.items())))


def _snapshot(
    counters: dict[tuple, float] | None = None,
    histograms: dict[tuple, tuple[list[float], list[int], float]] | None = None,
) -> dict[str, Any]:
    return {
        "counters": counters or {},
        "gauges": {},
        "histograms": histograms or {},
    }


def test_empty_snapshot_returns_zeroed_no_data_summary() -> None:
    payload = build_query_health(_snapshot(), generated_at="now")

    assert payload["generated_at"] == "now"
    assert payload["total_queries"] == 0
    assert payload["error_count"] == 0
    assert payload["error_rate"] is None
    assert payload["slow_query_count"] == 0
    assert payload["verdict"] == VERDICT_NO_DATA
    assert payload["kinds"] == []
    assert payload["recent_slow_queries"] == []
    assert isinstance(QueryHealthOut(**payload), QueryHealthOut)


def test_totals_percentiles_and_kind_breakdown_aggregate_histograms() -> None:
    select_key = _histogram_key(
        QUERY_DURATION_HISTOGRAM,
        {"kind": KIND_SELECT},
    )
    insert_key = _histogram_key(
        QUERY_DURATION_HISTOGRAM,
        {"kind": KIND_INSERT},
    )
    counters = {
        _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 10.0,
        _counter_key(QUERY_COUNTER, {"kind": KIND_INSERT}): 5.0,
    }
    histograms = {
        # Ten 1s SELECT observations: p50 750ms, p95 975ms, p99 995ms.
        select_key: ([0.5, 1.0, 2.0], [0, 10, 10], 10.0),
        # Five 0.25s INSERT observations: mean 250ms, p95 475ms.
        insert_key: ([0.5, 1.0, 2.0], [5, 5, 5], 1.25),
    }
    payload = build_query_health(
        _snapshot(counters=counters, histograms=histograms),
        generated_at="now",
    )

    assert payload["total_queries"] == 15
    assert payload["error_count"] == 0
    assert payload["error_rate"] == 0.0
    assert payload["slow_query_count"] == 0
    assert payload["mean_latency_ms"] == 750.0
    assert payload["p50_latency_ms"] == 625.0
    assert payload["p95_latency_ms"] == 962.5
    assert payload["p99_latency_ms"] == pytest.approx(992.5)

    assert [row["kind"] for row in payload["kinds"]] == [KIND_SELECT, KIND_INSERT]
    select_row = payload["kinds"][0]
    assert select_row["query_count"] == 10
    assert select_row["error_count"] == 0
    assert select_row["error_rate"] == 0.0
    assert select_row["mean_latency_ms"] == 1000.0
    assert select_row["p95_latency_ms"] == 975.0
    insert_row = payload["kinds"][1]
    assert insert_row["query_count"] == 5
    assert insert_row["mean_latency_ms"] == 250.0
    assert isinstance(QueryHealthOut(**payload), QueryHealthOut)


def test_error_rate_counts_errors_per_kind_and_clamps_above_one() -> None:
    counters = {
        _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 10.0,
        _counter_key(QUERY_ERROR_COUNTER, {"kind": KIND_SELECT}): 12.0,
        _counter_key(QUERY_ERROR_COUNTER, {"kind": KIND_OTHER}): 2.0,
    }
    payload = build_query_health(_snapshot(counters=counters), generated_at="now")

    # Errors exceed queries (mid-snapshot race / failed-before-count): the
    # overall and per-kind rates clamp to 1.0 instead of 1.2.
    assert payload["total_queries"] == 10
    assert payload["error_count"] == 14
    assert payload["error_rate"] == 1.0
    select_row = next(row for row in payload["kinds"] if row["kind"] == KIND_SELECT)
    assert select_row["error_rate"] == 1.0
    assert isinstance(QueryHealthOut(**payload), QueryHealthOut)


def test_slow_query_count_comes_from_counter_and_ring_is_sanitised() -> None:
    counters = {
        _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 4.0,
        _counter_key(SLOW_QUERY_COUNTER, {"kind": KIND_SELECT}): 2.0,
    }
    slow_queries = [
        {
            "kind": KIND_SELECT,
            "statement": "SELECT * FROM projects",
            "duration_ms": 512.0,
            "at": "2026-08-11T00:00:00Z",
        },
        {"kind": KIND_OTHER, "statement": "bad", "duration_ms": -1.0, "at": "x"},
        {"kind": KIND_SELECT, "statement": "SELECT 1", "duration_ms": 300.0, "at": ""},
        "not-a-dict",
    ]
    payload = build_query_health(
        _snapshot(counters=counters),
        slow_queries=slow_queries,
        limit=10,
        generated_at="now",
    )

    assert payload["slow_query_count"] == 2
    assert len(payload["recent_slow_queries"]) == 2
    assert payload["recent_slow_queries"][0]["statement"] == "SELECT * FROM projects"
    assert payload["recent_slow_queries"][0]["duration_ms"] == 512.0
    assert isinstance(QueryHealthOut(**payload), QueryHealthOut)


def test_recent_slow_queries_respect_limit() -> None:
    slow_queries = [
        {
            "kind": KIND_SELECT,
            "statement": f"SELECT {index}",
            "duration_ms": float(index),
            "at": "now",
        }
        for index in range(5)
    ]
    payload = build_query_health(
        _snapshot(),
        slow_queries=slow_queries,
        limit=2,
        generated_at="now",
    )
    assert len(payload["recent_slow_queries"]) == 2


def test_verdict_thresholds_map_to_health_watch_degraded() -> None:
    healthy_counters = {
        _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 10.0,
    }
    fast_hist = {
        _histogram_key(
            QUERY_DURATION_HISTOGRAM,
            {"kind": KIND_SELECT},
        ): ([0.05], [10], 0.25),
    }
    healthy = build_query_health(
        _snapshot(counters=healthy_counters, histograms=fast_hist),
        generated_at="now",
    )
    assert healthy["verdict"] == VERDICT_HEALTHY

    slow_hist = {
        _histogram_key(
            QUERY_DURATION_HISTOGRAM,
            {"kind": KIND_SELECT},
        ): ([0.3], [10], 3.0),
    }
    watch = build_query_health(
        _snapshot(counters=healthy_counters, histograms=slow_hist),
        generated_at="now",
    )
    assert watch["verdict"] == VERDICT_WATCH

    degraded_counters = {
        _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 10.0,
        _counter_key(QUERY_ERROR_COUNTER, {"kind": KIND_SELECT}): 1.0,
    }
    degraded = build_query_health(
        _snapshot(counters=degraded_counters, histograms=fast_hist),
        generated_at="now",
    )
    assert degraded["verdict"] == VERDICT_DEGRADED


def test_route_returns_typed_summary_from_registry_and_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _snapshot(
        counters={
            _counter_key(QUERY_COUNTER, {"kind": KIND_SELECT}): 7.0,
            _counter_key(SLOW_QUERY_COUNTER, {"kind": KIND_SELECT}): 1.0,
        },
        histograms={
            _histogram_key(
                QUERY_DURATION_HISTOGRAM,
                {"kind": KIND_SELECT},
            ): ([0.1, 0.5, 1.0], [7, 7, 7], 0.7),
        },
    )
    ring = [
        {
            "kind": KIND_SELECT,
            "statement": "SELECT * FROM simulations",
            "duration_ms": 300.0,
            "at": "2026-08-11T00:00:00Z",
        }
    ]
    monkeypatch.setattr(metrics, "snapshot", lambda: fixture)
    monkeypatch.setattr(
        system_health_module,
        "slow_queries_snapshot",
        lambda limit=None: ring,
    )

    payload = system_health_module.query_health(limit=5)
    assert payload["total_queries"] == 7
    assert payload["slow_query_count"] == 1
    assert payload["kinds"][0]["kind"] == KIND_SELECT
    assert payload["recent_slow_queries"][0]["statement"] == "SELECT * FROM simulations"
    assert isinstance(QueryHealthOut(**payload), QueryHealthOut)
