"""Unit tests for app.core.metrics.

Covers the in-process registry and Prometheus text rendering. These run
without DB / Redis / Celery so they're safe to execute anywhere.
"""
from __future__ import annotations

from app.core.metrics import _Metrics


def test_counter_increments_and_renders():
    m = _Metrics()
    m.inc_counter("hits_total", {"path": "/a"})
    m.inc_counter("hits_total", {"path": "/a"})
    m.inc_counter("hits_total", {"path": "/b"})
    out = m.render()
    assert 'hits_total{path="/a"} 2' in out
    assert 'hits_total{path="/b"} 1' in out


def test_gauge_set_replaces_value():
    m = _Metrics()
    m.set_gauge("queue_depth", 5)
    m.set_gauge("queue_depth", 12)
    out = m.render()
    assert "queue_depth 12" in out
    # The first value should not appear after the gauge is overwritten.
    assert "queue_depth 5" not in out


def test_histogram_buckets_are_cumulative_and_monotonic():
    m = _Metrics()
    m.observe("latency_seconds", 0.3)
    m.observe("latency_seconds", 1.5)
    m.observe("latency_seconds", 100.0)
    out = m.render()
    # 0.3 falls in le=0.5
    assert 'latency_seconds_bucket{le="0.5"} 1' in out
    # 0.3 and 1.5 both fall in le=2
    assert 'latency_seconds_bucket{le="2"} 2' in out
    # All three fall in le=+Inf
    assert 'latency_seconds_bucket{le="+Inf"} 3' in out
    # Sum is the sum of observed values
    assert "latency_seconds_sum 101.8" in out
    # Count is the total number of observations
    assert "latency_seconds_count 3" in out


def test_label_values_are_escaped():
    m = _Metrics()
    m.inc_counter("weird", {"k": 'a"b\\c\nd'})
    out = m.render()
    # Quote, backslash, and newline must be escaped per the Prometheus spec.
    assert 'weird{k="a\\"b\\\\c\\nd"}' in out


def test_render_includes_help_and_type_lines():
    m = _Metrics()
    m.inc_counter("my_counter")
    out = m.render()
    assert "# HELP my_counter my_counter" in out
    assert "# TYPE my_counter counter" in out


def test_helper_shortcuts_produce_expected_lines():
    m = _Metrics()
    m.sim_started()
    m.sim_completed(duration_seconds=8.0)
    m.sim_failed()
    m.claude_call(model="grok-3-mini", task="assumption_extraction")
    m.set_active_simulations(2)
    m.set_db_pool_checked_out(4)
    m.set_celery_workers_online(1)
    out = m.render()
    assert 'thecee_simulations_total{status="started"} 1' in out
    assert 'thecee_simulations_total{status="completed"} 1' in out
    assert 'thecee_simulations_total{status="failed"} 1' in out
    assert (
        'thecee_llm_calls_total{model="grok-3-mini",task="assumption_extraction"} 1'
        in out
    )
    assert "thecee_active_simulations 2" in out
    assert "thecee_db_pool_checked_out 4" in out
    assert "thecee_celery_workers_online 1" in out
    # The duration observation should land in the le=10 bucket.
    assert 'thecee_simulation_duration_seconds_bucket{le="10"} 1' in out


def test_http_request_bumps_counter_and_histogram():
    m = _Metrics()
    m.http_request("GET", "/projects/{id}", "2xx", 0.043)
    m.http_request("GET", "/projects/{id}", "2xx", 0.087)
    m.http_request("POST", "/projects/{id}/simulate", "2xx", 12.3)
    m.http_request("GET", "/projects/{id}", "4xx", 0.005)
    m.http_request("GET", "/projects/{id}", "5xx", 1.2)
    out = m.render()

    # Counter: each (method, path, status) tuple is its own series.
    assert (
        'thecee_http_requests_total{method="GET",path="/projects/{id}",status="2xx"} 2'
        in out
    )
    assert (
        'thecee_http_requests_total{method="GET",path="/projects/{id}",status="4xx"} 1'
        in out
    )
    assert (
        'thecee_http_requests_total{method="GET",path="/projects/{id}",status="5xx"} 1'
        in out
    )
    assert (
        'thecee_http_requests_total{method="POST",path="/projects/{id}/simulate",status="2xx"} 1'
        in out
    )

    # Histogram: the {id} path got 4 GET observations; the le=0.5 bucket
    # should hold the 3 sub-500ms responses and the le=2 bucket the 1.2s one.
    assert (
        'thecee_http_request_duration_seconds_bucket{le="0.5",method="GET",path="/projects/{id}"} 3'
        in out
    )
    assert (
        'thecee_http_request_duration_seconds_bucket{le="2",method="GET",path="/projects/{id}"} 4'
        in out
    )
    assert (
        'thecee_http_request_duration_seconds_count{method="GET",path="/projects/{id}"} 4'
        in out
    )

    # Histogram count + sum should agree with the sum of observed values.
    # 0.043 + 0.087 + 0.005 + 1.2 = 1.335
    assert (
        'thecee_http_request_duration_seconds_sum{method="GET",path="/projects/{id}"} 1.335'
        in out
    )
