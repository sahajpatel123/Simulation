"""Pure response-cache health digest builder.

``app.core.response_cache`` records every cache read / write / invalidation
into the in-process metrics registry with bounded labels (namespace, result,
and invalidation scope). This module turns that raw snapshot into the
``/system/cache-health`` digest: per-namespace hit/miss/error counts, write
and invalidation error counts, hit and error rates, live Redis key counts
(supplied by the route layer), and a HEALTHY / WATCH / DEGRADED / NO_DATA /
UNCONFIGURED verdict.

The builder is pure-Python (no DB, no Redis, no I/O) so it is verifiable
without FastAPI or a live cache. Multi-worker deployments scrape each
replica individually, matching the request-health / query-health endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.metrics import (
    CACHE_INVALIDATION_COUNTER,
    CACHE_READ_COUNTER,
    CACHE_WRITE_COUNTER,
)
from app.core.response_cache import (
    RESULT_ERROR,
    RESULT_HIT,
    RESULT_MISS,
    RESULT_SUCCESS,
    RESULT_UNCONFIGURED,
)

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_NO_DATA: str = "NO_DATA"
VERDICT_UNCONFIGURED: str = "UNCONFIGURED"

# Error-rate bands. WATCH flags more than 1% of configured cache operations
# failing; DEGRADED means more than 5% are failing.
WATCH_ERROR_RATE: float = 0.01
DEGRADED_ERROR_RATE: float = 0.05


def _safe_count(value: Any, default: int = 0) -> int:
    """Coerce a metric count to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else 0


def _grouped_counts(
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    name: str,
    label_names: tuple[str, ...],
) -> dict[tuple[str, ...], int]:
    """Sum one counter's values grouped by the given label values."""
    grouped: dict[tuple[str, ...], int] = {}
    for (counter_name, label_items), value in counters.items():
        if counter_name != name:
            continue
        labels = dict(label_items)
        key = tuple(
            str(labels.get(label_name) or "")
            for label_name in label_names
        )
        grouped[key] = grouped.get(key, 0) + _safe_count(value)
    return grouped


def _rate(numerator: int, denominator: int) -> float | None:
    """Return a rounded rate in ``[0, 1]`` or ``None`` for no denominator."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _verdict(
    *,
    redis_configured: bool,
    configured_operations: int,
    read_error_rate: float | None,
    write_error_rate: float | None,
    invalidation_error_rate: float | None,
    unconfigured_operations: int,
) -> str:
    if not redis_configured:
        return VERDICT_UNCONFIGURED
    if configured_operations <= 0 and unconfigured_operations > 0:
        return VERDICT_WATCH
    if configured_operations <= 0:
        return VERDICT_NO_DATA
    rates = [
        rate
        for rate in (
            read_error_rate,
            write_error_rate,
            invalidation_error_rate,
        )
        if rate is not None
    ]
    if any(rate > DEGRADED_ERROR_RATE for rate in rates):
        return VERDICT_DEGRADED
    if unconfigured_operations > 0 or any(
        rate > WATCH_ERROR_RATE for rate in rates
    ):
        return VERDICT_WATCH
    return VERDICT_HEALTHY


def build_cache_health(
    snapshot: dict[str, Any] | None = None,
    *,
    key_counts: dict[str, int] | None = None,
    redis_configured: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the response-cache health digest from a metrics snapshot.

    Args:
        snapshot: Output of ``metrics.snapshot()`` (counters / gauges /
            histograms). ``None`` / missing sections are treated as empty.
        key_counts: Live Redis key counts by namespace from
            ``app.core.response_cache.current_key_counts()``, or ``None``
            when Redis is unavailable / the scan failed.
        redis_configured: Whether a Redis client was available when the
            route sampled ``current_key_counts``.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``CacheHealthOut`` schema.
    """
    snapshot = snapshot or {}
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
        snapshot.get("counters") or {}
    )

    reads = _grouped_counts(
        counters, CACHE_READ_COUNTER, ("namespace", "result")
    )
    writes = _grouped_counts(
        counters, CACHE_WRITE_COUNTER, ("namespace", "result")
    )
    invalidations = _grouped_counts(
        counters,
        CACHE_INVALIDATION_COUNTER,
        ("namespace", "scope", "result"),
    )

    # Fold each counter family into per-namespace result buckets.
    read_by_ns: dict[str, dict[str, int]] = {}
    for (namespace, result), count in reads.items():
        bucket = read_by_ns.setdefault(namespace, {})
        bucket[result] = bucket.get(result, 0) + count
    write_by_ns: dict[str, dict[str, int]] = {}
    for (namespace, result), count in writes.items():
        bucket = write_by_ns.setdefault(namespace, {})
        bucket[result] = bucket.get(result, 0) + count
    invalidation_by_ns: dict[str, dict[str, int]] = {}
    for (namespace, _scope, result), count in invalidations.items():
        bucket = invalidation_by_ns.setdefault(namespace, {})
        bucket[result] = bucket.get(result, 0) + count

    namespace_names = sorted(
        set(read_by_ns) | set(write_by_ns) | set(invalidation_by_ns)
    )

    rows: list[dict[str, Any]] = []
    totals: dict[str, int] = {
        "reads": 0,
        "hits": 0,
        "misses": 0,
        "read_errors": 0,
        "unconfigured_reads": 0,
        "writes": 0,
        "write_errors": 0,
        "unconfigured_writes": 0,
        "invalidations": 0,
        "invalidation_errors": 0,
        "unconfigured_invalidations": 0,
    }

    for namespace in namespace_names:
        read_bucket = read_by_ns.get(namespace, {})
        write_bucket = write_by_ns.get(namespace, {})
        invalidation_bucket = invalidation_by_ns.get(namespace, {})

        hits = read_bucket.get(RESULT_HIT, 0)
        misses = read_bucket.get(RESULT_MISS, 0)
        read_errors = read_bucket.get(RESULT_ERROR, 0)
        unconfigured_reads = read_bucket.get(RESULT_UNCONFIGURED, 0)
        reads_total = hits + misses + read_errors + unconfigured_reads
        configured_reads = hits + misses + read_errors

        write_errors = write_bucket.get(RESULT_ERROR, 0)
        write_successes = write_bucket.get(RESULT_SUCCESS, 0)
        unconfigured_writes = write_bucket.get(RESULT_UNCONFIGURED, 0)
        writes_total = (
            write_errors + write_successes + unconfigured_writes
        )
        configured_writes = write_errors + write_successes

        invalidation_errors = invalidation_bucket.get(RESULT_ERROR, 0)
        invalidation_successes = invalidation_bucket.get(
            RESULT_SUCCESS, 0
        )
        unconfigured_invalidations = invalidation_bucket.get(
            RESULT_UNCONFIGURED, 0
        )
        invalidations_total = (
            invalidation_errors
            + invalidation_successes
            + unconfigured_invalidations
        )
        configured_invalidations = (
            invalidation_errors + invalidation_successes
        )

        rows.append(
            {
                "namespace": namespace,
                "reads": reads_total,
                "hits": hits,
                "misses": misses,
                "read_error_count": read_errors,
                "unconfigured_read_count": unconfigured_reads,
                "hit_rate": _rate(hits, configured_reads),
                "read_error_rate": _rate(read_errors, configured_reads),
                "writes": writes_total,
                "write_error_count": write_errors,
                "unconfigured_write_count": unconfigured_writes,
                "write_error_rate": _rate(
                    write_errors, configured_writes
                ),
                "invalidations": invalidations_total,
                "invalidation_error_count": invalidation_errors,
                "unconfigured_invalidation_count": (
                    unconfigured_invalidations
                ),
                "invalidation_error_rate": _rate(
                    invalidation_errors, configured_invalidations
                ),
                "current_keys": (
                    _safe_count(key_counts.get(namespace))
                    if key_counts is not None
                    else None
                ),
            }
        )

        totals["reads"] += reads_total
        totals["hits"] += hits
        totals["misses"] += misses
        totals["read_errors"] += read_errors
        totals["unconfigured_reads"] += unconfigured_reads
        totals["writes"] += writes_total
        totals["write_errors"] += write_errors
        totals["unconfigured_writes"] += unconfigured_writes
        totals["invalidations"] += invalidations_total
        totals["invalidation_errors"] += invalidation_errors
        totals["unconfigured_invalidations"] += (
            unconfigured_invalidations
        )

    configured_reads = (
        totals["hits"] + totals["misses"] + totals["read_errors"]
    )
    configured_writes = (
        totals["writes"] - totals["unconfigured_writes"]
    )
    configured_invalidations = (
        totals["invalidations"] - totals["unconfigured_invalidations"]
    )
    configured_operations = (
        configured_reads + configured_writes + configured_invalidations
    )
    unconfigured_operations = (
        totals["unconfigured_reads"]
        + totals["unconfigured_writes"]
        + totals["unconfigured_invalidations"]
    )

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "redis_configured": bool(redis_configured),
        "verdict": _verdict(
            redis_configured=bool(redis_configured),
            configured_operations=configured_operations,
            read_error_rate=_rate(
                totals["read_errors"], configured_reads
            ),
            write_error_rate=_rate(
                totals["write_errors"], configured_writes
            ),
            invalidation_error_rate=_rate(
                totals["invalidation_errors"],
                configured_invalidations,
            ),
            unconfigured_operations=unconfigured_operations,
        ),
        "total_reads": totals["reads"],
        "total_hits": totals["hits"],
        "total_misses": totals["misses"],
        "read_error_count": totals["read_errors"],
        "unconfigured_read_count": totals["unconfigured_reads"],
        "hit_rate": _rate(totals["hits"], configured_reads),
        "read_error_rate": _rate(
            totals["read_errors"], configured_reads
        ),
        "total_writes": totals["writes"],
        "write_error_count": totals["write_errors"],
        "unconfigured_write_count": totals["unconfigured_writes"],
        "write_error_rate": _rate(
            totals["write_errors"], configured_writes
        ),
        "total_invalidations": totals["invalidations"],
        "invalidation_error_count": totals["invalidation_errors"],
        "unconfigured_invalidation_count": totals[
            "unconfigured_invalidations"
        ],
        "invalidation_error_rate": _rate(
            totals["invalidation_errors"],
            configured_invalidations,
        ),
        "current_keys": (
            sum(_safe_count(value) for value in key_counts.values())
            if key_counts is not None
            else None
        ),
        "namespaces": rows,
    }


__all__ = [
    "DEGRADED_ERROR_RATE",
    "VERDICT_DEGRADED",
    "VERDICT_HEALTHY",
    "VERDICT_NO_DATA",
    "VERDICT_UNCONFIGURED",
    "VERDICT_WATCH",
    "WATCH_ERROR_RATE",
    "build_cache_health",
]
