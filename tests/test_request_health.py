"""Tests for the per-route request-health digest endpoint.

The digest is a pure read over the in-process metrics registry that already
feeds ``/metrics``. These tests pin the histogram percentile interpolation,
error-rate accounting, filtering/sorting, empty-snapshot behaviour and the
route contract so the SRE dashboard can rely on stable numbers.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.core.metrics import metrics
from app.core.request_health import build_request_health
from app.schemas.system_health import RequestHealthOut

# Importing ``app.api.v1.system_health`` pulls in the whole API router, which
# imports the billing router and the real ``razorpay`` SDK. On Python 3.12 the
# installed SDK fails on ``pkg_resources``; stub it the same way the other
# route tests do before any API-route import.
if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub


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


def test_empty_snapshot_returns_zeroed_summary() -> None:
    payload = build_request_health(_snapshot(), generated_at="now")

    assert payload["generated_at"] == "now"
    assert payload["total_requests"] == 0
    assert payload["total_errors"] == 0
    assert payload["overall_error_rate"] is None
    assert payload["route_count"] == 0
    assert payload["routes"] == []
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)


def test_percentiles_interpolate_within_histogram_buckets() -> None:
    # Ten 1-second observations: buckets [0.5, 1, 2, 5, 10] have cumulative
    # counts [0, 10, 10, 10, 10] and a running sum of 10s.
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/projects/{id}"},
        ): ([0.5, 1.0, 2.0, 5.0, 10.0], [0, 10, 10, 10, 10], 10.0),
    }
    payload = build_request_health(
        _snapshot(histograms=histograms),
        generated_at="now",
    )

    row = payload["routes"][0]
    assert row["request_count"] == 10
    assert row["error_count"] == 0
    assert row["error_rate"] == 0.0
    assert row["mean_latency_ms"] == 1000.0
    # p50 target is the 5th observation -> halfway inside [0.5s, 1s].
    assert row["p50_latency_ms"] == 750.0
    assert row["p95_latency_ms"] == 975.0
    assert row["p99_latency_ms"] == 995.0
    assert row["max_bucket_ms"] == 10000.0


def test_percentiles_use_first_bucket_for_fast_observations() -> None:
    # Ten 0.25s observations fall inside the first bucket [0.5s, ...].
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "POST", "path": "/simulations"},
        ): ([0.5, 1.0, 2.0], [10, 10, 10], 2.5),
    }
    payload = build_request_health(
        _snapshot(histograms=histograms),
        generated_at="now",
    )

    row = payload["routes"][0]
    assert row["mean_latency_ms"] == 250.0
    assert row["p50_latency_ms"] == 250.0
    # p95/p99 ranks land inside the first (wide) bucket, so the approximation
    # interpolates toward its upper bound rather than assuming all values sit
    # at the bucket's lower edge.
    assert row["p95_latency_ms"] == 475.0
    assert row["p99_latency_ms"] == 495.0


def test_error_rate_and_totals_account_for_5xx_and_other() -> None:
    route_a = {
        "method": "GET",
        "path": "/projects/{id}",
    }
    route_b = {
        "method": "POST",
        "path": "/simulations",
    }
    counters = {
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_a["method"], "path": route_a["path"], "status": "2xx"},
        ): 90.0,
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_a["method"], "path": route_a["path"], "status": "4xx"},
        ): 5.0,
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_a["method"], "path": route_a["path"], "status": "5xx"},
        ): 5.0,
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_b["method"], "path": route_b["path"], "status": "5xx"},
        ): 10.0,
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_b["method"], "path": route_b["path"], "status": "other"},
        ): 2.0,
        _counter_key(
            "thecee_http_requests_total",
            {"method": route_b["method"], "path": route_b["path"], "status": "2xx"},
        ): 88.0,
    }
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            route_a,
        ): ([0.5, 1.0], [100, 100], 100.0),
        _histogram_key(
            "thecee_http_request_duration_seconds",
            route_b,
        ): ([0.5, 1.0], [100, 100], 100.0),
    }
    payload = build_request_health(
        _snapshot(counters=counters, histograms=histograms),
        generated_at="now",
    )

    assert payload["total_requests"] == 200
    assert payload["total_errors"] == 17  # 5xx(5) + 5xx(10) + other(2)
    assert payload["overall_error_rate"] == pytest.approx(17 / 200)
    by_path = {row["path"]: row for row in payload["routes"]}
    assert by_path["/projects/{id}"]["error_count"] == 5
    assert by_path["/projects/{id}"]["error_rate"] == 0.05
    assert by_path["/simulations"]["error_count"] == 12
    assert by_path["/simulations"]["error_rate"] == 0.12


def test_min_requests_filters_and_limit_caps_sorted_routes() -> None:
    histograms = {}
    specs = [
        ("GET", "/fast", [10, 10], 10.0),
        ("GET", "/slow", [10, 10], 90.0),
        ("GET", "/rare", [2, 2], 2.0),
        ("GET", "/medium", [10, 10], 50.0),
    ]
    for method, path, counts, total in specs:
        histograms[_histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": method, "path": path},
        )] = ([0.5, 10.0], counts, total)

    payload = build_request_health(
        _snapshot(histograms=histograms),
        limit=2,
        min_requests=5,
        generated_at="now",
    )

    assert payload["route_count"] == 2
    assert [row["path"] for row in payload["routes"]] == [
        "/slow",  # p95 highest (mean 9s)
        "/medium",
    ]
    assert payload["total_requests"] == 32  # all routes, not just the top 2


def test_malformed_histograms_keep_request_count_but_null_latencies() -> None:
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/empty-buckets"},
        ): ([], [], 0.0),
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/mismatched"},
        ): ([0.5, 1.0], [5], 1.0),
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/zero-observations"},
        ): ([0.5, 1.0], [0, 0], 0.0),
    }
    payload = build_request_health(
        _snapshot(histograms=histograms),
        generated_at="now",
    )

    # Empty / zero-observation histograms are filtered out; a histogram with
    # mismatched buckets still reports the request count it knows, with null
    # latency statistics (it cannot be trusted for percentiles).
    assert payload["route_count"] == 1
    assert payload["total_requests"] == 5
    row = payload["routes"][0]
    assert row["path"] == "/mismatched"
    assert row["request_count"] == 5
    assert row["mean_latency_ms"] is None
    assert row["p50_latency_ms"] is None
    assert row["p95_latency_ms"] is None
    assert row["p99_latency_ms"] is None
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)


def test_route_returns_typed_summary_from_registry_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _snapshot(
        histograms={
            _histogram_key(
                "thecee_http_request_duration_seconds",
                {"method": "GET", "path": "/projects/{id}"},
            ): ([0.5, 1.0], [7, 7], 7.0),
        },
    )
    monkeypatch.setattr(metrics, "snapshot", lambda: fixture)

    from app.api.v1.system_health import request_health

    payload = request_health(limit=5, min_requests=1)
    assert payload["route_count"] == 1
    assert payload["routes"][0]["path"] == "/projects/{id}"
    assert payload["routes"][0]["request_count"] == 7
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)


def test_snapshot_race_cannot_produce_error_rate_above_one() -> None:
    """A counter/histogram snapshot taken mid-request must not 500 the digest.

    ``metrics.http_request()`` bumps the status counter and observes the
    latency histogram in two separate lock acquisitions, so a snapshot can
    briefly see more error counters than histogram observations (a 5xx
    counter bumped before its histogram entry). The digest clamps per-route
    errors to the observed request count instead of emitting error_rate > 1,
    which ``RequestHealthOut`` would reject and turn into a 500.
    """
    route = {"method": "GET", "path": "/projects/{id}"}
    counters = {
        _counter_key(
            "thecee_http_requests_total",
            {**route, "status": "5xx"},
        ): 2.0,
    }
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            route,
        ): ([0.5, 1.0], [1, 1], 0.25),
    }
    payload = build_request_health(
        _snapshot(counters=counters, histograms=histograms),
        generated_at="now",
    )

    row = payload["routes"][0]
    assert row["request_count"] == 1
    assert row["error_count"] == 1
    assert row["error_rate"] == 1.0
    assert payload["total_requests"] == 1
    assert payload["total_errors"] == 1
    assert payload["overall_error_rate"] == 1.0
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)


def test_malformed_negative_counts_never_break_schema() -> None:
    """Negative or non-monotonic counts are clamped so totals stay valid."""
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/negative"},
        ): ([0.5, 1.0], [-5, -5], -1.0),
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "GET", "path": "/non-monotonic"},
        ): ([0.5, 1.0], [5, 3], 4.0),
    }
    payload = build_request_health(
        _snapshot(histograms=histograms),
        min_requests=0,
        generated_at="now",
    )

    assert payload["total_requests"] == 3  # negative route contributes 0
    assert payload["total_errors"] == 0
    assert payload["overall_error_rate"] == 0.0
    by_path = {row["path"]: row for row in payload["routes"]}
    assert by_path["/negative"]["request_count"] == 0
    assert by_path["/negative"]["mean_latency_ms"] is None
    assert by_path["/non-monotonic"]["request_count"] == 3
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)


def test_negative_latency_inputs_are_clamped_not_rejected() -> None:
    """Negative histogram sums / buckets never produce schema-invalid rows."""
    histograms = {
        _histogram_key(
            "thecee_http_request_duration_seconds",
            {"method": "POST", "path": "/simulations"},
        ): ([-2.0, -1.0], [10, 10], -50.0),
    }
    payload = build_request_health(
        _snapshot(histograms=histograms),
        generated_at="now",
    )

    row = payload["routes"][0]
    assert row["request_count"] == 10
    assert row["mean_latency_ms"] == 0.0
    assert row["p50_latency_ms"] == 0.0
    assert row["p95_latency_ms"] == 0.0
    assert row["p99_latency_ms"] == 0.0
    assert row["max_bucket_ms"] == 0.0
    assert isinstance(RequestHealthOut(**payload), RequestHealthOut)
