"""Simulation pipeline health digest builder and DB collector.

The other ``/system`` digests probe infrastructure (database, Redis,
Celery, LLM calls, response cache). This module answers the
product-level question: are simulations actually completing, how long do
they take, and what is failing? It reads the ``simulations`` table
bounded by a recency window and rolls status counts, completion-latency
percentiles, coarse failure buckets, a daily trend, and a HEALTHY / WATCH
/ DEGRADED / NO_DATA verdict.

The builder is pure-Python (no DB, no I/O) so the verdict and percentile
logic is unit-testable without a database. The collector is a thin
SQLAlchemy read layer that returns a snapshot for the builder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.simulation import Simulation

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_NO_DATA: str = "NO_DATA"

REASON_FAILURE_RATE_HIGH: str = "failure_rate_high"
REASON_NO_TERMINAL_RUNS: str = "no_terminal_runs"
REASON_STUCK_RUNNING: str = "stuck_running"

DEFAULT_WINDOW_DAYS: int = 7
MAX_WINDOW_DAYS: int = 30
DEFAULT_RECENT_FAILURES_LIMIT: int = 10
MAX_RECENT_FAILURES_LIMIT: int = 50

# Failure-rate bands: WATCH flags more than 10% of terminal runs failing;
# DEGRADED means more than half of terminal runs fail.
WATCH_FAILURE_RATE: float = 0.10
DEGRADED_FAILURE_RATE: float = 0.50

# A RUNNING simulation older than this is considered stuck, because the
# worker either died mid-run or the task is wedged in the queue.
STUCK_RUNNING_HOURS: float = 24.0

TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED"})

# Coarse failure buckets, in classification order. The first matching
# keyword wins, so ``timeout`` beats ``llm_api`` and ``database`` beats
# the generic infrastructure keywords.
_FAILURE_BUCKET_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timeout", "timed out", "timedout")),
    (
        "llm_api",
        (
            "grok",
            "llm",
            "model call",
            "openai",
            "anthropic",
            "claude",
            "rate limit",
        ),
    ),
    (
        "database",
        ("sqlalchemy", "psycopg", "database", "postgres", "db connection"),
    ),
    (
        "infrastructure",
        (
            "redis",
            "celery",
            "broker",
            "worker lost",
            "connection refused",
        ),
    ),
)

BUCKET_NO_ERROR_MESSAGE: str = "no_error_message"
BUCKET_OTHER: str = "other"

_ERROR_SNIPPET_LIMIT: int = 200


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _safe_float(value: Any) -> float | None:
    """Coerce a value to a non-negative float or return ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0.0 else None


def _rate(numerator: int, denominator: int) -> float | None:
    """Return a rounded rate in ``[0, 1]`` or ``None`` for no denominator."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile of an ascending list, or ``None`` when empty."""
    if not sorted_values:
        return None
    rank = max(1, min(len(sorted_values), int(percentile * len(sorted_values) + 0.5)))
    return round(sorted_values[rank - 1], 3)


def _iso(value: Any) -> str | None:
    """Serialise a datetime to ISO-8601, passing strings through untouched."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _coerce_dt(value: Any) -> datetime | None:
    """Coerce a row timestamp to an aware datetime, or ``None``."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _truncate(value: Any, limit: int = _ERROR_SNIPPET_LIMIT) -> str:
    """Coerce an error message to a bounded string."""
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def classify_failure(error_message: str | None) -> str:
    """Bucket an error message into one coarse, dashboard-safe category."""
    message = (error_message or "").strip().lower()
    if not message:
        return BUCKET_NO_ERROR_MESSAGE
    for bucket, keywords in _FAILURE_BUCKET_RULES:
        if any(keyword in message for keyword in keywords):
            return bucket
    return BUCKET_OTHER


def _latency_stats(durations_ms: list[float]) -> dict[str, Any]:
    """Aggregate completion latencies into digest stats."""
    if not durations_ms:
        return {
            "count": 0,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    sorted_values = sorted(durations_ms)
    return {
        "count": len(sorted_values),
        "mean_ms": round(sum(sorted_values) / len(sorted_values), 3),
        "p50_ms": _percentile(sorted_values, 0.50),
        "p95_ms": _percentile(sorted_values, 0.95),
        "p99_ms": _percentile(sorted_values, 0.99),
        "min_ms": round(sorted_values[0], 3),
        "max_ms": round(sorted_values[-1], 3),
    }


def _failure_buckets(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll failure rows into coarse buckets sorted by count desc."""
    buckets: dict[str, dict[str, Any]] = {}
    for failure in failures:
        bucket_name = classify_failure(failure.get("error_message"))
        bucket = buckets.setdefault(
            bucket_name,
            {"bucket": bucket_name, "count": 0, "latest_at": None, "sample_error": ""},
        )
        bucket["count"] += 1
        created_at = failure.get("created_at")
        if created_at and (bucket["latest_at"] is None or created_at > bucket["latest_at"]):
            bucket["latest_at"] = created_at
        sample = _truncate(failure.get("error_message"))
        if sample and not bucket["sample_error"]:
            bucket["sample_error"] = sample
    rows = list(buckets.values())
    rows.sort(key=lambda row: (-row["count"], row["bucket"]))
    return rows


def _daily_trend(
    daily_counts: dict[str, dict[str, int]],
    *,
    window_days: int,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    """Zero-fill and order the daily trend across the recency window."""
    end_date = generated_at.astimezone(UTC).date()
    start_date = end_date - timedelta(days=max(1, window_days) - 1)
    trend: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.isoformat()
        counts = daily_counts.get(key, {})
        trend.append(
            {
                "date": key,
                "created": _safe_int(counts.get("created")),
                "completed": _safe_int(counts.get("completed")),
                "failed": _safe_int(counts.get("failed")),
            }
        )
        cursor += timedelta(days=1)
    return trend


def build_simulation_health(
    *,
    status_counts: dict[str, int] | None = None,
    completed_durations_ms: list[float] | None = None,
    failures: list[dict[str, Any]] | None = None,
    daily_counts: dict[str, dict[str, int]] | None = None,
    oldest_running_at: str | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    generated_at: str | None = None,
    watch_failure_rate: float = WATCH_FAILURE_RATE,
    degraded_failure_rate: float = DEGRADED_FAILURE_RATE,
    stuck_running_hours: float = STUCK_RUNNING_HOURS,
) -> dict[str, Any]:
    """Compose the simulation-pipeline health digest from a snapshot.

    Pure and deterministic (no DB / I/O), so the verdict, rate and
    percentile logic is unit-testable without a database.
    """
    status_counts = status_counts or {}
    completed_durations_ms = completed_durations_ms or []
    failures = failures or []
    daily_counts = daily_counts or {}

    total = sum(_safe_int(value) for value in status_counts.values())
    completed = _safe_int(status_counts.get("COMPLETED"))
    failed = _safe_int(status_counts.get("FAILED"))
    terminal = completed + failed
    failure_rate = _rate(failed, terminal) if terminal > 0 else None

    verdict = VERDICT_HEALTHY
    reasons: list[str] = []
    if total <= 0:
        verdict = VERDICT_NO_DATA
    elif terminal <= 0:
        verdict = VERDICT_WATCH
        reasons.append(REASON_NO_TERMINAL_RUNS)
    elif failure_rate is not None and failure_rate >= degraded_failure_rate:
        verdict = VERDICT_DEGRADED
        reasons.append(REASON_FAILURE_RATE_HIGH)
    elif failure_rate is not None and failure_rate >= watch_failure_rate:
        verdict = VERDICT_WATCH
        reasons.append(REASON_FAILURE_RATE_HIGH)

    oldest_running = _coerce_dt(oldest_running_at)
    if oldest_running is not None:
        age_hours = (
            datetime.now(UTC) - oldest_running
        ).total_seconds() / 3600.0
        if age_hours > max(0.0, stuck_running_hours):
            if verdict != VERDICT_DEGRADED:
                verdict = VERDICT_WATCH
            reasons.append(REASON_STUCK_RUNNING)

    generated_dt = _coerce_dt(generated_at) or datetime.now(UTC)

    return {
        "generated_at": generated_at or generated_dt.isoformat(),
        "window_days": max(1, window_days),
        "total_simulations": total,
        "status_breakdown": {
            str(status): _safe_int(count) for status, count in status_counts.items()
        },
        "completed_count": completed,
        "failed_count": failed,
        "terminal_count": terminal,
        "completion_rate": _rate(completed, terminal) if terminal > 0 else None,
        "failure_rate": failure_rate,
        "latency": _latency_stats(
            [
                value
                for value in completed_durations_ms
                if _safe_float(value) is not None
            ]
        ),
        "failure_buckets": _failure_buckets(failures),
        "recent_failures": [
            {
                "simulation_id": _safe_int(failure.get("simulation_id")),
                "project_id": _safe_int(failure.get("project_id")),
                "created_at": _iso(failure.get("created_at")),
                "error_message": _truncate(failure.get("error_message")),
            }
            for failure in failures
        ],
        "daily_trend": _daily_trend(
            daily_counts,
            window_days=max(1, window_days),
            generated_at=generated_dt,
        ),
        "oldest_running_at": _iso(oldest_running_at),
        "verdict": verdict,
        "reasons": reasons,
    }


def collect_simulation_snapshot(
    db: Session,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    recent_failures_limit: int = DEFAULT_RECENT_FAILURES_LIMIT,
) -> dict[str, Any]:
    """Read the bounded ``simulations`` window and build a raw snapshot.

    Only column projections are fetched (never ``results_json``), and the
    recency window is enforced in SQL so the digest stays cheap even as the
    table grows. All aggregation is done here in Python so the digest does
    not depend on PostgreSQL-specific percentile/date functions.
    """
    cutoff = datetime.now(UTC) - timedelta(days=max(1, window_days))
    rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.status,
            Simulation.created_at,
            Simulation.updated_at,
            Simulation.error_message,
        )
        .filter(Simulation.created_at >= cutoff)
        .all()
    )

    status_counts: dict[str, int] = {}
    durations: list[float] = []
    daily: dict[str, dict[str, int]] = {}
    failure_rows: list[dict[str, Any]] = []
    oldest_running: datetime | None = None

    for row in rows:
        status = str(getattr(row, "status", "") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        created = _coerce_dt(getattr(row, "created_at", None))
        updated = _coerce_dt(getattr(row, "updated_at", None))

        if created is not None:
            created_date = created.astimezone(UTC).date().isoformat()
            day = daily.setdefault(
                created_date, {"created": 0, "completed": 0, "failed": 0}
            )
            day["created"] += 1

        if status == "COMPLETED":
            terminal_at = updated or created
            if terminal_at is not None:
                terminal_date = terminal_at.astimezone(UTC).date().isoformat()
                day = daily.setdefault(
                    terminal_date, {"created": 0, "completed": 0, "failed": 0}
                )
                day["completed"] += 1
            if created is not None and updated is not None:
                duration_ms = (updated - created).total_seconds() * 1000.0
                if duration_ms >= 0.0:
                    durations.append(duration_ms)
        elif status == "FAILED":
            terminal_at = updated or created
            if terminal_at is not None:
                terminal_date = terminal_at.astimezone(UTC).date().isoformat()
                day = daily.setdefault(
                    terminal_date, {"created": 0, "completed": 0, "failed": 0}
                )
                day["failed"] += 1
            failure_rows.append(
                {
                    "simulation_id": _safe_int(getattr(row, "id", None)),
                    "project_id": _safe_int(getattr(row, "project_id", None)),
                    "created_at": _iso(created),
                    "error_message": _truncate(getattr(row, "error_message", None)),
                }
            )
        elif status == "RUNNING" and created is not None:
            if oldest_running is None or created < oldest_running:
                oldest_running = created

    failure_rows.sort(
        key=lambda failure: failure.get("created_at") or "",
        reverse=True,
    )
    return {
        "status_counts": status_counts,
        "completed_durations_ms": durations,
        "failures": failure_rows[: max(1, recent_failures_limit)],
        "daily_counts": daily,
        "oldest_running_at": _iso(oldest_running),
    }


__all__ = [
    "BUCKET_NO_ERROR_MESSAGE",
    "BUCKET_OTHER",
    "DEFAULT_RECENT_FAILURES_LIMIT",
    "DEFAULT_WINDOW_DAYS",
    "DEGRADED_FAILURE_RATE",
    "MAX_RECENT_FAILURES_LIMIT",
    "MAX_WINDOW_DAYS",
    "REASON_FAILURE_RATE_HIGH",
    "REASON_NO_TERMINAL_RUNS",
    "REASON_STUCK_RUNNING",
    "STUCK_RUNNING_HOURS",
    "TERMINAL_STATUSES",
    "VERDICT_DEGRADED",
    "VERDICT_HEALTHY",
    "VERDICT_NO_DATA",
    "VERDICT_WATCH",
    "WATCH_FAILURE_RATE",
    "build_simulation_health",
    "classify_failure",
    "collect_simulation_snapshot",
]
