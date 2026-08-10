"""Pure LLM call health digest builder.

``app.core.claude_client`` records every successful Grok call as a counter
(``thecee_llm_calls_total``) plus a latency histogram
(``thecee_llm_duration_seconds``), and every failed / timed-out call as a
separate failure counter (``thecee_llm_failures_total``) with a coarse
reason label. This module turns that raw metrics snapshot into the
``/system/llm-health`` digest: attempt / success / failure totals, success
and failure rates, mean / p50 / p95 / p99 latency, per-model and per-task
breakdowns, a failure-reason breakdown, and a HEALTHY / WATCH / DEGRADED /
NO_DATA verdict.

The builder is pure-Python (no DB, no I/O) so it is verifiable without
FastAPI, PostgreSQL, or a live LLM provider. Multi-worker deployments scrape
each replica individually, matching the request-health / query-health
endpoints.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.core.metrics import LLM_DURATION_HISTOGRAM
from app.core.query_health import (
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
)

LLM_CALLS_COUNTER: str = "thecee_llm_calls_total"
LLM_FAILURES_COUNTER: str = "thecee_llm_failures_total"

# Verdict thresholds. WATCH flags a failure rate over 1% or a p95 over 5s;
# DEGRADED means more than 10% of attempts failed or the p95 approaches the
# 30s client timeout.
WATCH_FAILURE_RATE: float = 0.01
DEGRADED_FAILURE_RATE: float = 0.10
WATCH_P95_MS: float = 5000.0
DEGRADED_P95_MS: float = 20000.0

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
    cumulative count reaches the rank target as the query-health digest, so
    the observability endpoints report consistent percentile math.
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


def _merge_hist(
    existing: tuple[list[float], list[int], float] | None,
    new: tuple[list[float], list[int], float],
) -> tuple[list[float], list[int], float]:
    """Fold one histogram into an aggregate, skipping mismatched buckets."""
    buckets, counts, total = new
    if existing is None:
        return (list(buckets), list(counts), _safe_float(total, 0.0) or 0.0)
    existing_buckets, existing_counts, existing_total = existing
    if existing_buckets != buckets:
        return existing
    return (
        existing_buckets,
        [existing + count for existing, count in zip(existing_counts, counts)],
        existing_total + (_safe_float(total, 0.0) or 0.0),
    )


def _counter_grouped(
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    name: str,
) -> dict[tuple[str, str], int]:
    """Sum one counter's values grouped by the (model, task) label pair."""
    totals: dict[tuple[str, str], int] = {}
    for (counter_name, label_items), value in counters.items():
        if counter_name != name:
            continue
        labels = dict(label_items)
        key = (
            str(labels.get("model") or ""),
            str(labels.get("task") or ""),
        )
        totals[key] = totals.get(key, 0) + _safe_count(value)
    return totals


def _failure_grouped(
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float],
) -> dict[tuple[str, str, str], int]:
    """Sum failure-counter values grouped by (model, task, reason)."""
    totals: dict[tuple[str, str, str], int] = {}
    for (counter_name, label_items), value in counters.items():
        if counter_name != LLM_FAILURES_COUNTER:
            continue
        labels = dict(label_items)
        key = (
            str(labels.get("model") or ""),
            str(labels.get("task") or ""),
            str(labels.get("reason") or "unknown"),
        )
        totals[key] = totals.get(key, 0) + _safe_count(value)
    return totals


def _histogram_grouped(
    histograms: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        tuple[list[float], list[int], float],
    ],
) -> dict[tuple[str, str], tuple[list[float], list[int], float]]:
    """Merge LLM-duration histograms by the (model, task) label pair."""
    merged: dict[tuple[str, str], tuple[list[float], list[int], float]] = {}
    for (name, label_items), histogram in histograms.items():
        if name != LLM_DURATION_HISTOGRAM:
            continue
        labels = dict(label_items)
        key = (
            str(labels.get("model") or ""),
            str(labels.get("task") or ""),
        )
        merged[key] = _merge_hist(merged.get(key), histogram)
    return merged


def _aggregate_overall_histogram(
    histograms: dict[tuple[str, str], tuple[list[float], list[int], float]],
) -> tuple[list[float], list[int], float]:
    """Blend all label sets into one overall latency histogram."""
    overall_buckets: list[float] = []
    overall_counts: list[int] = []
    overall_sum = 0.0
    for buckets, counts, total in histograms.values():
        if not overall_buckets:
            overall_buckets = list(buckets)
            overall_counts = list(counts)
        elif overall_buckets == buckets:
            overall_counts = [existing + count for existing, count in zip(overall_counts, counts)]
        overall_sum += _safe_float(total, 0.0) or 0.0
    return overall_buckets, overall_counts, overall_sum


def _rate_rows(
    *,
    grouped_calls: dict[tuple[str, str], int],
    grouped_failures: dict[tuple[str, str, str], int],
    grouped_histograms: dict[
        tuple[str, str],
        tuple[list[float], list[int], float],
    ],
    limit: int,
    axis: int,
) -> list[dict[str, Any]]:
    """Build per-model (axis=0) or per-task (axis=1) digest rows."""
    labels: dict[str, dict[str, int]] = {}
    hists: dict[str, tuple[list[float], list[int], float] | None] = {}
    for (model, task), count in grouped_calls.items():
        label = model if axis == 0 else task
        bucket = labels.setdefault(label, {"calls": 0, "failures": 0})
        bucket["calls"] += count
    for (model, task, reason), count in grouped_failures.items():
        label = model if axis == 0 else task
        bucket = labels.setdefault(label, {"calls": 0, "failures": 0})
        bucket["failures"] += count
    for (model, task), histogram in grouped_histograms.items():
        label = model if axis == 0 else task
        hists[label] = _merge_hist(hists.get(label), histogram)

    rows: list[dict[str, Any]] = []
    for label, bucket in labels.items():
        attempts = bucket["calls"] + bucket["failures"]
        if attempts <= 0:
            continue
        hist = hists.get(label)
        buckets, counts, total = hist if hist is not None else ([], [], 0.0)
        failure_rate = bucket["failures"] / attempts
        row: dict[str, Any] = {"model" if axis == 0 else "task": label}
        row.update(
            {
                "success_count": bucket["calls"],
                "failure_count": bucket["failures"],
                "attempt_count": attempts,
                "success_rate": round(1.0 - failure_rate, 6),
                "failure_rate": round(failure_rate, 6),
                "mean_latency_ms": _mean_ms(buckets, counts, total),
                "p50_latency_ms": _histogram_percentile_ms(buckets, counts, 50.0),
                "p95_latency_ms": _histogram_percentile_ms(buckets, counts, 95.0),
                "p99_latency_ms": _histogram_percentile_ms(buckets, counts, 99.0),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["attempt_count"],
            row["model" if axis == 0 else "task"],
        ),
        reverse=True,
    )
    return rows[:limit]


def _verdict(
    *,
    total_attempts: int,
    failure_rate: float | None,
    p95_ms: float | None,
) -> str:
    if total_attempts <= 0:
        return VERDICT_NO_DATA
    if failure_rate is not None and failure_rate > DEGRADED_FAILURE_RATE:
        return VERDICT_DEGRADED
    if p95_ms is not None and p95_ms > DEGRADED_P95_MS:
        return VERDICT_DEGRADED
    if failure_rate is not None and failure_rate > WATCH_FAILURE_RATE:
        return VERDICT_WATCH
    if p95_ms is not None and p95_ms > WATCH_P95_MS:
        return VERDICT_WATCH
    return VERDICT_HEALTHY


def build_llm_health(
    snapshot: dict[str, Any] | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the LLM call health digest from a metrics snapshot.

    Args:
        snapshot: Output of ``metrics.snapshot()`` (counters / gauges /
            histograms). ``None`` / missing sections are treated as empty.
        limit: Maximum number of models and tasks to return, sorted by
            attempt count descending.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``LLMHealthOut`` schema.
    """
    snapshot = snapshot or {}
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = snapshot.get("counters") or {}
    histograms: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        tuple[list[float], list[int], float],
    ] = snapshot.get("histograms") or {}
    if not isinstance(counters, dict):
        counters = {}
    if not isinstance(histograms, dict):
        histograms = {}

    grouped_calls = _counter_grouped(counters, LLM_CALLS_COUNTER)
    grouped_failures = _failure_grouped(counters)
    grouped_histograms = _histogram_grouped(histograms)

    total_calls = sum(grouped_calls.values())
    total_failures = sum(grouped_failures.values())
    total_attempts = total_calls + total_failures
    overall_buckets, overall_counts, overall_sum = _aggregate_overall_histogram(grouped_histograms)
    failure_rate = round(total_failures / total_attempts, 6) if total_attempts > 0 else None

    reason_totals: dict[str, int] = {}
    for (_model, _task, reason), count in grouped_failures.items():
        reason_totals[reason] = reason_totals.get(reason, 0) + count
    reasons = [
        {"reason": reason, "failure_count": count}
        for reason, count in sorted(
            reason_totals.items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
    ]

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "total_attempts": total_attempts,
        "success_count": total_calls,
        "failure_count": total_failures,
        "success_rate": (round(1.0 - failure_rate, 6) if failure_rate is not None else None),
        "failure_rate": failure_rate,
        "mean_latency_ms": _mean_ms(overall_buckets, overall_counts, overall_sum),
        "p50_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 50.0),
        "p95_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 95.0),
        "p99_latency_ms": _histogram_percentile_ms(overall_buckets, overall_counts, 99.0),
        "verdict": _verdict(
            total_attempts=total_attempts,
            failure_rate=failure_rate,
            p95_ms=_histogram_percentile_ms(overall_buckets, overall_counts, 95.0),
        ),
        "models": _rate_rows(
            grouped_calls=grouped_calls,
            grouped_failures=grouped_failures,
            grouped_histograms=grouped_histograms,
            limit=limit,
            axis=0,
        ),
        "tasks": _rate_rows(
            grouped_calls=grouped_calls,
            grouped_failures=grouped_failures,
            grouped_histograms=grouped_histograms,
            limit=limit,
            axis=1,
        ),
        "failure_reasons": reasons,
    }


__all__ = [
    "DEFAULT_LIMIT",
    "DEGRADED_FAILURE_RATE",
    "DEGRADED_P95_MS",
    "LLM_CALLS_COUNTER",
    "LLM_DURATION_HISTOGRAM",
    "LLM_FAILURES_COUNTER",
    "MAX_LIMIT",
    "WATCH_FAILURE_RATE",
    "WATCH_P95_MS",
    "build_llm_health",
]
