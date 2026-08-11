"""
In-process Prometheus-style metrics registry.

Lightweight, dependency-free. Counters and gauges live in module-level
dicts so a single worker process exposes consistent numbers; multi-worker
deployments scrape each replica individually (standard Prometheus model).

Naming follows Prometheus conventions: ``thecee_<subsystem>_<unit>``.

Usage:
    from app.core.metrics import metrics

    metrics.sim_started()
    metrics.sim_completed(duration_seconds=12.4)
    metrics.sim_failed()
    metrics.claude_call(model="grok-3-mini", task="assumption_extraction")
    metrics.set_active_simulations(3)
    metrics.set_db_pool_checked_out(7)
    metrics.set_celery_workers_online(2)

    # Render for /metrics endpoint
    text = metrics.render()
"""
from __future__ import annotations

import math
import threading
import time
from typing import Iterable

# Histogram name for successful LLM call latency. Shared with the LLM
# health digest (``app.core.llm_health``) so the recorded metric and the
# digest read the same key.
LLM_DURATION_HISTOGRAM: str = "thecee_llm_duration_seconds"

# Response-cache counters. Recorded by ``app.core.response_cache`` and
# summarised by ``app.core.cache_health`` into the /system/cache-health
# digest. Keeping the names here centralises metric naming so a rename
# cannot drift between the recorder and the reader.
CACHE_READ_COUNTER: str = "thecee_response_cache_reads_total"
CACHE_WRITE_COUNTER: str = "thecee_response_cache_writes_total"
CACHE_INVALIDATION_COUNTER: str = "thecee_response_cache_invalidations_total"

# Per-architect compute duration histogram. Recorded by
# ``app.simulation.conductor`` for every successful architect ``compute()`` so
# the signal that the persisted run-level rollup provides after completion is
# also visible live on ``/metrics``. Values are observed in seconds (the
# repo-wide convention for duration metrics); the persisted
# ``results_json["conductor_architect_timing"]`` payload keeps the same
# measurements in milliseconds.
ARCHITECT_DURATION_HISTOGRAM: str = "thecee_architect_compute_duration_seconds"

# Seconds buckets for the per-architect compute histogram. Architect
# ``compute()`` calls are pure in-process functions that typically take
# microseconds to a few milliseconds, so the first buckets cover that range
# and the tail captures the slow outliers an operator should investigate.
ARCHITECT_DURATION_BUCKETS_SECONDS: tuple[float, ...] = (
    0.001,
    0.002,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
)


class _Metrics:
    """Thread-safe in-process metrics store.

    All counter / gauge mutations take the same ``_lock`` so the snapshot
    rendered for ``/metrics`` is internally consistent — partial writes
    between two concurrent updates can't tear a label set.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        # Histograms: (bucket_upper, count, sum) keyed by metric+labels.
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            tuple[list[float], list[int], float],
        ] = {}

    # ------------------------------------------------------------------
    # Counter helpers
    # ------------------------------------------------------------------

    def inc_counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        value: float = 1.0,
    ) -> None:
        """Bump a counter by ``value`` (default 1)."""
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    # ------------------------------------------------------------------
    # Gauge helpers
    # ------------------------------------------------------------------

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge to an absolute value."""
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    # ------------------------------------------------------------------
    # Histogram helpers
    # ------------------------------------------------------------------

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        buckets: Iterable[float] = (0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    ) -> None:
        """Record a single observation in a histogram with the given buckets.

        Counts are stored CUMULATIVELY (``counts[i]`` is the number of
        observations with value <= ``buckets[i]``), matching the Prometheus
        exposition format directly. Storing the per-bucket delta would
        require an O(n) pre-pass on every render, so the cumulative form
        lets ``render()`` emit one line per bucket in a single pass.
        """
        key = self._key(name, labels)
        bucket_list = sorted(buckets)
        with self._lock:
            existing = self._histograms.get(key)
            if existing is None:
                # Fresh histogram: cumulative counts start at zero for every
                # bucket, and the running sum of observed values is 0.0.
                self._histograms[key] = (
                    list(bucket_list),
                    [0] * len(bucket_list),
                    0.0,
                )
                existing = self._histograms[key]
            bs, counts, total = existing
            for i, upper in enumerate(bs):
                if value <= upper:
                    counts[i] += 1
            self._histograms[key] = (bs, counts, total + value)

    # ------------------------------------------------------------------
    # Domain shortcuts — keep call sites short and the metric names
    # centralized so renames don't sprawl across the codebase.
    # ------------------------------------------------------------------

    def sim_started(self) -> None:
        self.inc_counter("thecee_simulations_total", {"status": "started"})

    def sim_completed(self, duration_seconds: float) -> None:
        self.inc_counter("thecee_simulations_total", {"status": "completed"})
        self.observe("thecee_simulation_duration_seconds", duration_seconds)

    def sim_failed(self) -> None:
        self.inc_counter("thecee_simulations_total", {"status": "failed"})

    def sim_cancelled(self) -> None:
        self.inc_counter("thecee_simulations_total", {"status": "cancelled"})

    def claude_call(self, model: str, task: str) -> None:
        self.inc_counter(
            "thecee_llm_calls_total",
            {"model": model, "task": task},
        )

    def claude_call_failure(self, model: str, task: str, reason: str) -> None:
        """Record one failed / timed-out / errored LLM call.

        Distinct counter from ``claude_call`` (success) so the
        dashboard can compute success-rate alerts. The ``reason``
        label is a coarse category (``"timeout"``,
        ``"api_error_4xx"``, ``"api_error_5xx"``,
        ``"api_error_unknown"``, ``"unexpected"``) so the cardinality
        stays bounded.
        """
        self.inc_counter(
            "thecee_llm_failures_total",
            {"model": model, "task": task, "reason": reason},
        )

    def claude_call_duration(
        self,
        model: str,
        task: str,
        duration_seconds: float,
    ) -> None:
        """Observe one successful LLM call's latency.

        Failures are deliberately excluded — timeouts would otherwise skew
        the digest's latency percentiles to the timeout ceiling. Use the
        failure counters for outage detection instead.
        """
        try:
            duration = float(duration_seconds)
        except (TypeError, ValueError):
            duration = 0.0
        self.observe(
            LLM_DURATION_HISTOGRAM,
            max(0.0, duration),
            labels={"model": model, "task": task},
        )

    def http_request(
        self,
        method: str,
        path: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Record one HTTP request: bump the per-route counter and observe
        its latency on the shared duration histogram.

        ``path`` should be the matched route template (``/projects/{id}``),
        not the raw URL — callers are responsible for normalisation so the
        label cardinality stays bounded.
        """
        labels = {"method": method, "path": path, "status": status}
        self.inc_counter("thecee_http_requests_total", labels)
        self.observe(
            "thecee_http_request_duration_seconds",
            duration_seconds,
            labels={"method": method, "path": path},
        )

    def response_cache_read(self, namespace: str, result: str) -> None:
        """Record one cache read attempt (``hit`` / ``miss`` / ``error`` /
        ``unconfigured``) for the digest builder."""
        self.inc_counter(
            CACHE_READ_COUNTER,
            {"namespace": namespace, "result": result},
        )

    def response_cache_write(self, namespace: str, result: str) -> None:
        """Record one cache write attempt (``success`` / ``error`` /
        ``unconfigured``)."""
        self.inc_counter(
            CACHE_WRITE_COUNTER,
            {"namespace": namespace, "result": result},
        )

    def response_cache_invalidation(
        self,
        namespace: str,
        scope: str,
        result: str,
    ) -> None:
        """Record one cache invalidation (scope ``user`` or ``all``)."""
        self.inc_counter(
            CACHE_INVALIDATION_COUNTER,
            {
                "namespace": namespace,
                "scope": scope,
                "result": result,
            },
        )

    def architect_compute(self, architect: str, duration_ms: float) -> None:
        """Observe one successful architect ``compute()`` wall-clock duration.

        The duration is accepted in milliseconds (the unit used by the
        persisted timing rollup) and converted to seconds for the histogram,
        matching the other duration metrics in this registry. Non-finite or
        negative durations are ignored so a bad timer can never skew the
        latency distribution.
        """
        try:
            duration = float(duration_ms)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(duration) or duration < 0.0:
            return
        self.observe(
            ARCHITECT_DURATION_HISTOGRAM,
            duration / 1000.0,
            labels={"architect": architect},
            buckets=ARCHITECT_DURATION_BUCKETS_SECONDS,
        )

    def snapshot(self) -> dict[str, object]:
        """Return deep-enough copies of all registry state for read-only consumers.

        Keys keep the internal tuple form
        ``(name, ((label_key, label_value), ...))``; histograms are
        ``(bucket_bounds, cumulative_counts, sum)`` triples. Consumers
        (e.g. the request-health summary endpoint) use this instead of
        reaching into the private ``_counters`` / ``_histograms`` dicts,
        and the copies make the snapshot safe to read outside the lock.
        """
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    key: (list(buckets), list(counts), total)
                    for key, (buckets, counts, total) in self._histograms.items()
                },
            }

    def set_active_simulations(self, n: int) -> None:
        self.set_gauge("thecee_active_simulations", n)

    def set_db_pool_checked_out(self, n: int) -> None:
        self.set_gauge("thecee_db_pool_checked_out", n)

    def set_db_pool_checkedin(self, n: int) -> None:
        self.set_gauge("thecee_db_pool_checked_in", n)

    def set_db_pool_overflow(self, n: int) -> None:
        self.set_gauge("thecee_db_pool_overflow", n)

    def set_db_pool_utilization(self, ratio: float) -> None:
        """Set pool utilization (checked-out / pool_size + overflow)."""
        self.set_gauge("thecee_db_pool_utilization", ratio)

    def set_db_server_connections(self, n: int) -> None:
        self.set_gauge("thecee_db_server_connections", n)

    def set_db_server_max_connections(self, n: int) -> None:
        self.set_gauge("thecee_db_server_max_connections", n)

    def set_db_server_connection_ratio(self, ratio: float) -> None:
        """Set server connection headroom (active / max_connections)."""
        self.set_gauge("thecee_db_server_connection_ratio", ratio)

    def set_celery_workers_online(self, n: int) -> None:
        self.set_gauge("thecee_celery_workers_online", n)

    def set_celery_queue_depth(self, queue: str, n: int) -> None:
        """Set the current broker queue depth for one Celery queue."""
        self.set_gauge("thecee_celery_queue_depth", n, {"queue": queue})

    def set_websocket_connections(self, n: int) -> None:
        """Set the live WebSocket listener count for simulation progress."""
        self.set_gauge("thecee_websocket_connections", n)

    def set_websocket_bridge_running(self, flag: bool) -> None:
        """Set whether the progress pub/sub subscriber loop is alive."""
        self.set_gauge("thecee_websocket_bridge_running", 1.0 if flag else 0.0)

    def set_websocket_redis_configured(self, flag: bool) -> None:
        """Set whether a Redis client is configured for the bridge."""
        self.set_gauge("thecee_websocket_redis_configured", 1.0 if flag else 0.0)

    def set_websocket_redis_reachable(self, flag: bool) -> None:
        """Set the live Redis reachability result for progress delivery."""
        self.set_gauge("thecee_websocket_redis_reachable", 1.0 if flag else 0.0)

    def set_websocket_last_publish_failure_age(self, seconds: float) -> None:
        """Set the age of the last progress publish failure (seconds)."""
        self.set_gauge(
            "thecee_websocket_last_publish_failure_age_seconds",
            seconds,
        )

    def set_websocket_unhealthy(self, flag: bool) -> None:
        """Set 1 when the delivery digest verdict is WATCH or DEGRADED."""
        self.set_gauge("thecee_websocket_unhealthy", 1.0 if flag else 0.0)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format (v0.0.4)."""
        lines: list[str] = []
        with self._lock:
            counters_snapshot = dict(self._counters)
            gauges_snapshot = dict(self._gauges)
            histograms_snapshot = {
                k: (list(v[0]), list(v[1]), v[2])
                for k, v in self._histograms.items()
            }

        # Counters
        for (name, label_items), value in sorted(counters_snapshot.items()):
            labels = dict(label_items)
            lines.append(self._format_line(name, "counter", value, labels))

        # Gauges
        for (name, label_items), value in sorted(gauges_snapshot.items()):
            labels = dict(label_items)
            lines.append(self._format_line(name, "gauge", value, labels))

        # Histograms. ``counts`` is stored CUMULATIVELY (each entry is the
        # number of observations with value <= its bucket boundary), so we
        # can emit the bucket line, the +Inf overflow, the total, and the
        # running sum directly — no per-render re-summation needed.
        for (name, label_items), (buckets, counts, total) in sorted(
            histograms_snapshot.items()
        ):
            labels = dict(label_items)
            for upper, cumulative in zip(buckets, counts):
                bucket_labels = {**labels, "le": _fmt_bucket(upper)}
                lines.append(
                    self._format_line(
                        name + "_bucket",
                        "histogram",
                        cumulative,
                        bucket_labels,
                    )
                )
            # The +Inf bucket equals the largest cumulative count; that is
            # the total number of observations on this label set.
            inf_total = counts[-1] if counts else 0
            inf_labels = {**labels, "le": "+Inf"}
            lines.append(
                self._format_line(
                    name + "_bucket",
                    "histogram",
                    inf_total,
                    inf_labels,
                )
            )
            lines.append(
                self._format_line(name + "_count", "counter", inf_total, labels)
            )
            lines.append(
                self._format_line(name + "_sum", "counter", total, labels)
            )

        # Process metrics — cheap to compute, useful for sanity.
        lines.append(
            "# HELP thecee_process_uptime_seconds Seconds since process start."
        )
        lines.append("# TYPE thecee_process_uptime_seconds gauge")
        lines.append(
            f"thecee_process_uptime_seconds {_process_uptime_seconds():.3f}"
        )

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _key(
        name: str, labels: dict[str, str] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        # Sort labels so equivalent label sets collide on the same key.
        items = tuple(sorted((labels or {}).items()))
        return (name, items)

    @staticmethod
    def _format_line(
        name: str,
        kind: str,
        value: float,
        labels: dict[str, str],
    ) -> str:
        # Help / type lines are emitted lazily: a metric with zero observations
        # still gets a header pair so Prometheus can ingest it without
        # "unknown metric" warnings.
        header = (
            f"# HELP {name} {name}\n"
            f"# TYPE {name} {kind}\n"
        )
        if not labels:
            return f"{header}{name} {_fmt_number(value)}"
        # Prometheus label values must escape backslash, double-quote, and newline.
        rendered = ",".join(
            f'{k}="{_escape(v)}"' for k, v in sorted(labels.items())
        )
        return f"{header}{name}{{{rendered}}} {_fmt_number(value)}"


# Module-level singleton — the standard Prometheus client pattern.
# Imported as ``metrics`` throughout the codebase.
metrics = _Metrics()


# ---------------------------------------------------------------------------
# Process start — used by the uptime gauge.
# ---------------------------------------------------------------------------
_PROCESS_STARTED = time.monotonic()


def _process_uptime_seconds() -> float:
    return time.monotonic() - _PROCESS_STARTED


def _fmt_number(v: float) -> str:
    # Prometheus accepts regular floats; trim to keep output compact.
    if v != v:  # NaN
        return "NaN"
    if v == float("inf"):
        return "+Inf"
    if v == float("-inf"):
        return "-Inf"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _fmt_bucket(upper: float) -> str:
    """Render a histogram bucket upper bound per Prometheus rules.

    Integers come out as ``5`` (not ``5.0``); infinity as ``+Inf`` (the
    cumulative bucket uses ``+Inf`` explicitly, so the ``inf`` case is
    only relevant for future per-bucket overflow).
    """
    if upper == float("inf"):
        return "+Inf"
    if upper == int(upper):
        return str(int(upper))
    return repr(upper)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
