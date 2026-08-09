"""
Pure per-route request-health summary builder.

Reads an in-process metrics snapshot (from ``app.core.metrics.metrics.snapshot()``)
and turns the raw HTTP counters + latency histograms into a human-readable
ops summary: per-route request count, error count/rate, and mean / p50 / p95 /
p99 latency, plus overall totals.

The Prometheus ``/metrics`` endpoint remains the canonical raw source; this
digest is the quick "what is slow / erroring right now?" answer for the
dashboard and for debugging without a Prometheus server.

The builder is pure-Python (no DB, no I/O) so it is verifiable without
FastAPI or PostgreSQL.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

# Metric names recorded by ``metrics.http_request``.
HTTP_REQUESTS_COUNTER: str = "thecee_http_requests_total"
HTTP_REQUEST_DURATION_HISTOGRAM: str = "thecee_http_request_duration_seconds"

# Status classes treated as errors for the digest. ``other`` covers malformed
# status codes (outside 100-599) which are never a success.
ERROR_STATUS_CLASSES: frozenset[str] = frozenset({"5xx", "other"})

# Default caps for the digest output.
DEFAULT_LIMIT: int = 15
DEFAULT_MIN_REQUESTS: int = 1
MAX_LIMIT: int = 100


def _safe_finite(value: Any, default: float | None = None) -> float | None:
    """Coerce to a finite float or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _histogram_percentile_ms(
    buckets: list[float],
    counts: list[int],
    percentile: float,
) -> float | None:
    """Approximate a latency percentile (ms) from cumulative histogram buckets.

    Counts are stored cumulatively (``counts[i]`` = observations <=
    ``buckets[i]``). The percentile is located by linear interpolation inside
    the first bucket whose cumulative count reaches the rank target, matching
    the standard histogram-percentile approximation used by Prometheus-style
    dashboards. Returns ``None`` when there are no observations.
    """
    if not buckets or not counts or len(buckets) != len(counts):
        return None
    total = counts[-1]
    if total <= 0:
        return None
    target = (percentile / 100.0) * total
    if target <= 0:
        return 0.0
    for index, cumulative in enumerate(counts):
        if cumulative <= 0:
            continue
        if target <= cumulative:
            lower_bound = 0.0 if index == 0 else buckets[index - 1]
            lower_count = 0 if index == 0 else counts[index - 1]
            upper_bound = buckets[index]
            span = cumulative - lower_count
            if span <= 0:
                value = upper_bound
            else:
                value = lower_bound + (
                    (target - lower_count) / span * (upper_bound - lower_bound)
                )
            return value * 1000.0
    # Rank beyond the last bucket: approximate with the last upper bound.
    return buckets[-1] * 1000.0


def _mean_ms(
    buckets: list[float],
    counts: list[int],
    total_sum: Any,
) -> float | None:
    """Mean latency in ms from the histogram's running sum."""
    if not buckets or not counts or len(buckets) != len(counts):
        return None
    total = counts[-1]
    if total <= 0:
        return None
    total_sum_finite = _safe_finite(total_sum)
    if total_sum_finite is None:
        return None
    return total_sum_finite / total * 1000.0


def build_request_health(
    snapshot: dict[str, Any] | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    min_requests: int = DEFAULT_MIN_REQUESTS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the request-health digest from a metrics snapshot.

    Args:
        snapshot: Output of ``metrics.snapshot()`` (counters / gauges /
            histograms). ``None`` / missing sections are treated as empty.
        limit: Maximum number of routes to return (sorted by p95 desc).
        min_requests: Only include routes with at least this many requests.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``RequestHealthOut`` schema:
        ``generated_at``, ``total_requests``, ``total_errors``,
        ``overall_error_rate``, ``route_count`` and ``routes``.
    """
    snapshot = snapshot or {}
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
        snapshot.get("counters") or {}
    )
    histograms: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        tuple[list[float], list[int], float],
    ] = (snapshot.get("histograms") or {})

    # Aggregate histogram entries by (method, path).
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for key, (buckets, counts, total_sum) in histograms.items():
        name, label_items = key
        if name != HTTP_REQUEST_DURATION_HISTOGRAM:
            continue
        labels = dict(label_items)
        method = labels.get("method", "")
        path = labels.get("path", "")
        if not method or not path:
            continue
        routes.setdefault((method, path), {
            "buckets": buckets,
            "counts": counts,
            "sum_seconds": total_sum,
            "error_count": 0,
        })

    # Attribute error counts from the status-class counters.
    for key, value in counters.items():
        name, label_items = key
        if name != HTTP_REQUESTS_COUNTER:
            continue
        labels = dict(label_items)
        if labels.get("status", "") not in ERROR_STATUS_CLASSES:
            continue
        method = labels.get("method", "")
        path = labels.get("path", "")
        row = routes.get((method, path))
        if row is not None:
            row["error_count"] += int(value)

    # Overall totals reflect the whole snapshot, not the filtered top-N.
    total_requests = 0
    total_errors = 0
    for (method, path), row in routes.items():
        request_count = row["counts"][-1] if row["counts"] else 0
        row["request_count"] = request_count
        total_requests += request_count
        total_errors += row["error_count"]

    overall_error_rate = (
        round(total_errors / total_requests, 6) if total_requests > 0 else None
    )

    rows: list[dict[str, Any]] = []
    for (method, path), row in routes.items():
        request_count = int(row["request_count"])
        if request_count < min_requests:
            continue
        error_count = int(row["error_count"])
        p50 = _histogram_percentile_ms(row["buckets"], row["counts"], 50.0)
        p95 = _histogram_percentile_ms(row["buckets"], row["counts"], 95.0)
        p99 = _histogram_percentile_ms(row["buckets"], row["counts"], 99.0)
        mean = _mean_ms(row["buckets"], row["counts"], row["sum_seconds"])
        rows.append({
            "method": method,
            "path": path,
            "request_count": request_count,
            "error_count": error_count,
            "error_rate": (
                round(error_count / request_count, 6)
                if request_count > 0 else None
            ),
            "mean_latency_ms": (
                round(mean, 3) if mean is not None else None
            ),
            "p50_latency_ms": round(p50, 3) if p50 is not None else None,
            "p95_latency_ms": round(p95, 3) if p95 is not None else None,
            "p99_latency_ms": round(p99, 3) if p99 is not None else None,
            "max_bucket_ms": (
                round(row["buckets"][-1] * 1000.0, 3)
                if row["buckets"] else None
            ),
        })

    # Sort by p95 descending (slowest routes first), then mean latency
    # descending as a tie-breaker (identical bucket shapes can produce the
    # same p95 approximation), then path for stability.
    rows.sort(
        key=lambda r: (
            r["p95_latency_ms"] is None,
            -(r["p95_latency_ms"] or 0.0),
            r["mean_latency_ms"] is None,
            -(r["mean_latency_ms"] or 0.0),
            r["path"],
            r["method"],
        )
    )
    limited = rows[:limit]

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "total_requests": int(total_requests),
        "total_errors": int(total_errors),
        "overall_error_rate": overall_error_rate,
        "route_count": len(limited),
        "routes": limited,
    }


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_MIN_REQUESTS",
    "ERROR_STATUS_CLASSES",
    "HTTP_REQUESTS_COUNTER",
    "HTTP_REQUEST_DURATION_HISTOGRAM",
    "MAX_LIMIT",
    "build_request_health",
]
