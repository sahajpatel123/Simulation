"""Pure DB query-health digest builder.

``app.core.query_metrics`` records every non-transactional statement on
the shared engine into the in-process metrics registry and keeps a
bounded ring of the slowest statements. This module turns that raw
snapshot into the ``/system/query-health`` digest: totals, error rate,
mean / p50 / p95 / p99 latency, per-kind breakdowns, a slow-query counter
and the recent slow statements, plus a HEALTHY / WATCH / DEGRADED /
NO_DATA verdict.

The builder is pure-Python (no DB, no I/O) so it is verifiable without
FastAPI or PostgreSQL.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.core.query_metrics import (
    KIND_OTHER,
    QUERY_COUNTER,
    QUERY_DURATION_HISTOGRAM,
    QUERY_ERROR_COUNTER,
    SLOW_QUERY_COUNTER,
)

VERDICT_NO_DATA: str = "NO_DATA"
VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"

# Verdict thresholds. The WATCH band flags a p95 over 250ms or an error
# rate over 1%; DEGRADED means a p95 over 1s or more than 5% failures.
WATCH_P95_MS: float = 250.0
DEGRADED_P95_MS: float = 1000.0
WATCH_ERROR_RATE: float = 0.01
DEGRADED_ERROR_RATE: float = 0.05

DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 50


def _safe_float(value: Any, default: float | None = None) -> float | None:
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


def _safe_count(value: Any, default: int = 0) -> int:
    """Coerce a metric count to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else 0


def _histogram_percentile_ms(
    buckets: list[float],
    counts: list[int],
    percentile: float,
) -> float | None:
    """Approximate a latency percentile (ms) from cumulative histogram buckets.

    Uses the same linear interpolation inside the first bucket whose
    cumulative count reaches the rank target as the request-health digest,
    so the two observability endpoints report consistent percentile math.
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
                value = lower_bound + ((target - lower_count) / span * (upper_bound - lower_bound))
            return value * 1000.0
    return buckets[-1] * 1000.0


def _mean_ms(
    buckets: list[float],
    counts: list[int],
    total_sum: Any,
) -> float | None:
    """Mean latency in ms from a histogram's running sum."""
    if not buckets or not counts or len(buckets) != len(counts):
        return None
    total = counts[-1]
    if total <= 0:
        return None
    total_sum_finite = _safe_float(total_sum)
    if total_sum_finite is None:
        return None
    return total_sum_finite / total * 1000.0


def _aggregate_histograms(
    histograms: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        tuple[list[float], list[int], float],
    ],
) -> dict[str, tuple[list[float], list[int], float]]:
    """Merge histogram entries by the ``kind`` label.

    Defensive: the metrics registry should hold exactly one histogram per
    kind, but merging makes the digest robust to multiple label sets and
    keeps the shape compatible with ``metrics.snapshot()``.
    """
    merged: dict[str, tuple[list[float], list[int], float]] = {}
    for (name, label_items), (buckets, counts, total) in histograms.items():
        if name != QUERY_DURATION_HISTOGRAM:
            continue
        labels = dict(label_items)
        kind = labels.get("kind") or KIND_OTHER
        if kind not in merged:
            merged[kind] = (list(buckets), list(counts), _safe_float(total, 0.0) or 0.0)
            continue
        existing_buckets, existing_counts, existing_total = merged[kind]
        if existing_buckets != buckets:
            continue
        merged[kind] = (
            existing_buckets,
            [existing_count + count for existing_count, count in zip(existing_counts, counts)],
            existing_total + (_safe_float(total, 0.0) or 0.0),
        )
    return merged


def _counter_totals(
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    name: str,
) -> dict[str, int]:
    """Sum one counter's values grouped by the ``kind`` label."""
    totals: dict[str, int] = {}
    for (counter_name, label_items), value in counters.items():
        if counter_name != name:
            continue
        labels = dict(label_items)
        kind = labels.get("kind") or KIND_OTHER
        totals[kind] = totals.get(kind, 0) + _safe_count(value)
    return totals


def _verdict(
    *,
    total_queries: int,
    error_rate: float | None,
    p95_ms: float | None,
) -> str:
    if total_queries <= 0:
        return VERDICT_NO_DATA
    if error_rate is not None and error_rate > DEGRADED_ERROR_RATE:
        return VERDICT_DEGRADED
    if p95_ms is not None and p95_ms > DEGRADED_P95_MS:
        return VERDICT_DEGRADED
    if error_rate is not None and error_rate > WATCH_ERROR_RATE:
        return VERDICT_WATCH
    if p95_ms is not None and p95_ms > WATCH_P95_MS:
        return VERDICT_WATCH
    return VERDICT_HEALTHY


def _sanitise_slow_queries(
    slow_queries: list[dict[str, Any]] | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Copy and coerce slow-query entries into the schema-safe shape."""
    cleaned: list[dict[str, Any]] = []
    for entry in slow_queries or []:
        if not isinstance(entry, dict):
            continue
        duration_ms = _safe_float(entry.get("duration_ms"))
        if duration_ms is None or duration_ms < 0.0:
            continue
        cleaned.append(
            {
                "kind": str(entry.get("kind") or KIND_OTHER),
                "statement": str(entry.get("statement") or ""),
                "duration_ms": round(duration_ms, 3),
                "at": str(entry.get("at") or ""),
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def build_query_health(
    snapshot: dict[str, Any] | None = None,
    slow_queries: list[dict[str, Any]] | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the DB query-health digest from a metrics snapshot.

    Args:
        snapshot: Output of ``metrics.snapshot()`` (counters / gauges /
            histograms). ``None`` / missing sections are treated as empty.
        slow_queries: Bounded ring from
            ``app.core.query_metrics.slow_queries_snapshot()``.
        limit: Maximum number of recent slow queries to return.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``QueryHealthOut`` schema.
    """
    snapshot = snapshot or {}
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = snapshot.get("counters") or {}
    histograms: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        tuple[list[float], list[int], float],
    ] = snapshot.get("histograms") or {}

    query_totals = _counter_totals(counters, QUERY_COUNTER)
    error_totals = _counter_totals(counters, QUERY_ERROR_COUNTER)
    slow_totals = _counter_totals(counters, SLOW_QUERY_COUNTER)
    merged_histograms = _aggregate_histograms(histograms)

    total_queries = sum(query_totals.values())
    total_errors = sum(error_totals.values())
    total_slow = sum(slow_totals.values())
    error_rate = min(1.0, total_errors / total_queries) if total_queries > 0 else None

    overall_buckets: list[float] = []
    overall_counts: list[int] = []
    overall_sum = 0.0
    for buckets, counts, total in merged_histograms.values():
        if not overall_buckets:
            overall_buckets = list(buckets)
            overall_counts = list(counts)
        elif overall_buckets == buckets:
            overall_counts = [existing + count for existing, count in zip(overall_counts, counts)]
        overall_sum += _safe_float(total, 0.0) or 0.0

    kinds: list[dict[str, Any]] = []
    all_kinds = sorted(
        set(query_totals) | set(error_totals) | set(merged_histograms),
    )
    for kind in all_kinds:
        kind_queries = query_totals.get(kind, 0)
        kind_errors = error_totals.get(kind, 0)
        buckets, counts, total = merged_histograms.get(
            kind,
            ([], [], 0.0),
        )
        kinds.append(
            {
                "kind": kind,
                "query_count": kind_queries,
                "error_count": kind_errors,
                "error_rate": (min(1.0, kind_errors / kind_queries) if kind_queries > 0 else None),
                "mean_latency_ms": _mean_ms(buckets, counts, total),
                "p95_latency_ms": _histogram_percentile_ms(buckets, counts, 95.0),
            }
        )
    kinds.sort(key=lambda item: item["query_count"], reverse=True)

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "total_queries": total_queries,
        "error_count": total_errors,
        "error_rate": error_rate,
        "slow_query_count": total_slow,
        "mean_latency_ms": _mean_ms(overall_buckets, overall_counts, overall_sum),
        "p50_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 50.0),
        "p95_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 95.0),
        "p99_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 99.0),
        "verdict": _verdict(
            total_queries=total_queries,
            error_rate=error_rate,
            p95_ms=_histogram_percentile_ms(overall_buckets, overall_counts, 95.0),
        ),
        "kinds": kinds,
        "recent_slow_queries": _sanitise_slow_queries(slow_queries, limit=limit),
    }


__all__ = [
    "DEFAULT_LIMIT",
    "DEGRADED_ERROR_RATE",
    "DEGRADED_P95_MS",
    "MAX_LIMIT",
    "VERDICT_DEGRADED",
    "VERDICT_HEALTHY",
    "VERDICT_NO_DATA",
    "VERDICT_WATCH",
    "WATCH_ERROR_RATE",
    "WATCH_P95_MS",
    "build_query_health",
]
