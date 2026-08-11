"""System health summary endpoint."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import llm_health as llm_health_module
from app.core import query_health as query_health_module
from app.core import response_cache as response_cache_module
from app.core import worker_health as worker_health_module
from app.core.cache_health import build_cache_health
from app.core.deps import get_db
from app.core.metrics import metrics
from app.core.query_metrics import slow_queries_snapshot
from app.core.rate_limiter import rate_limit
from app.core.redis_client import get_redis_client
from app.core.request_health import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_REQUESTS,
    MAX_LIMIT,
    build_request_health,
)
from app.schemas.system_health import (
    CacheHealthOut,
    LLMHealthOut,
    QueryHealthOut,
    RequestHealthOut,
    SystemHealthOut,
    WorkerHealthOut,
)
from app.worker import celery_app

router = APIRouter(prefix="/system", tags=["system"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def build_health_summary(
    database: dict[str, Any],
    redis: dict[str, Any],
    worker: dict[str, Any],
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Compose the health summary from the three service probes."""
    db_ok = database.get("status") == "ok"
    redis_ok = redis.get("status") in {"ok", "unconfigured"}
    healthy = bool(db_ok and redis_ok)
    return {
        "status": "ok" if healthy else "degraded",
        "healthy": healthy,
        "checked_at": checked_at or datetime.now(UTC).isoformat(),
        "checks": {
            "database": database,
            "redis": redis,
            "worker": worker,
        },
    }


def _db_status(db: Session) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {"status": "ok", "latency_ms": round(max(0.0, latency_ms), 3)}


def _redis_status() -> dict[str, Any]:
    client = get_redis_client()
    if client is None:
        return {"status": "unconfigured"}
    started = time.perf_counter()
    try:
        client.ping()
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {"status": "ok", "latency_ms": round(max(0.0, latency_ms), 3)}


def _worker_status() -> dict[str, Any]:
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_workers = inspect.ping() or {}
        return {
            "worker_reachable": bool(active_workers),
            "workers_online": len(active_workers),
        }
    except Exception as exc:
        return {"worker_reachable": False, "workers_online": 0, "error": str(exc)[:200]}


@router.get(
    "/health",
    summary="Combined database, Redis, and worker health probe",
    responses=_JSON_200,
    response_model=SystemHealthOut,
)
def system_health(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return one aggregate health summary for the API's services."""
    return build_health_summary(
        database=_db_status(db),
        redis=_redis_status(),
        worker=_worker_status(),
    )


@router.get(
    "/request-health",
    summary="In-process per-route request health (latency percentiles + error rates)",
    responses=_JSON_200,
    response_model=RequestHealthOut,
)
def request_health(
    limit: int = Query(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum number of routes to return (slowest p95 first).",
    ),
    min_requests: int = Query(
        default=DEFAULT_MIN_REQUESTS,
        ge=0,
        description="Only include routes with at least this many requests.",
    ),
) -> dict[str, Any]:
    """Return a human-readable per-route latency + error-rate digest.

    Reads the in-process metrics registry that also feeds ``/metrics``, so
    it reflects the current process's traffic without a Prometheus server:
    request counts, error counts/rates, and mean / p50 / p95 / p99 latency
    per matched route template.
    """
    return build_request_health(
        metrics.snapshot(),
        limit=limit,
        min_requests=min_requests,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/query-health",
    summary="In-process database query health (latency percentiles, error rates, slow statements)",
    responses=_JSON_200,
    response_model=QueryHealthOut,
)
def query_health(
    limit: int = Query(
        default=query_health_module.DEFAULT_LIMIT,
        ge=1,
        le=query_health_module.MAX_LIMIT,
        description="Maximum number of recent slow statements to return.",
    ),
) -> dict[str, Any]:
    """Return a digest of the process's SQL query performance.

    Reads the in-process metrics registry filled by the engine-level query
    listener (``app.core.query_metrics``): per-kind SELECT / INSERT /
    UPDATE / DELETE / OTHER counts and latency percentiles, error counts
    and rate, a slow-query counter, and the bounded ring of the slowest
    statements observed by this process. Statement text is the parameterised
    SQL template only — bound values are never captured.
    """
    return query_health_module.build_query_health(
        metrics.snapshot(),
        slow_queries=slow_queries_snapshot(limit=limit),
        limit=limit,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/llm-health",
    summary="In-process LLM call health (success rates, failure reasons, latency percentiles)",
    responses=_JSON_200,
    response_model=LLMHealthOut,
)
def llm_health(
    limit: int = Query(
        default=llm_health_module.DEFAULT_LIMIT,
        ge=1,
        le=llm_health_module.MAX_LIMIT,
        description="Maximum number of models and tasks to return (most attempted first).",
    ),
) -> dict[str, Any]:
    """Return a digest of this process's LLM (Grok) call performance.

    Reads the in-process metrics registry filled by
    ``app.core.claude_client``: successful call counts and latency
    histograms per model / task, plus the failure counter with coarse
    reasons (timeout / api_error_* / unexpected). Attempts are successes
    plus failures, so a total outage shows up as a 100% failure rate rather
    than a silent zero.
    """
    return llm_health_module.build_llm_health(
        metrics.snapshot(),
        limit=limit,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/cache-health",
    summary="Response-cache health (hit/miss/error rates + live key counts)",
    responses=_JSON_200,
    response_model=CacheHealthOut,
    # Scans the Redis key space (non-blocking SCAN), so bound dashboard
    # polling the way the other observability digests are bounded. The
    # limiter fails open because this endpoint diagnoses the cache: when
    # Redis is down, the Redis-backed limiter must not 503 the one probe
    # that would report the outage.
    dependencies=[
        Depends(rate_limit(limit=10, window_s=60, fail_open=True))
    ],
)
def cache_health() -> dict[str, Any]:
    """Return a digest of the response cache's in-process activity.

    Reads the metrics recorded by ``app.core.response_cache``: per-namespace
    hit / miss / error counts, write and invalidation error counts, hit and
    error rates, plus the number of live ``rcache:*`` keys currently held in
    Redis (sampled with SCAN, never returned). When Redis is unconfigured
    the digest reports ``UNCONFIGURED``; when the process has not exercised
    the cache it reports ``NO_DATA``.
    """
    key_counts, redis_configured = response_cache_module.current_key_counts()
    return build_cache_health(
        metrics.snapshot(),
        key_counts=key_counts,
        redis_configured=redis_configured,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/worker-health",
    summary=(
        "Celery worker and queue health (backlog depth, concurrency, "
        "in-flight tasks)"
    ),
    responses=_JSON_200,
    response_model=WorkerHealthOut,
    # Probes every worker (ping/stats/active/reserved/scheduled/queues) and
    # LLENs each queue on the broker, so bound dashboard polling the way the
    # other observability digests are bounded. Fails open so the probe that
    # would report a broker outage is not 503ed by the Redis-backed limiter.
    dependencies=[
        Depends(rate_limit(limit=10, window_s=60, fail_open=True))
    ],
)
def worker_health(
    backlog_threshold: int = Query(
        default=worker_health_module.DEFAULT_BACKLOG_THRESHOLD,
        ge=1,
        le=worker_health_module.MAX_BACKLOG_THRESHOLD,
        description=(
            "Total broker queue depth at which the digest reports WATCH "
            "instead of HEALTHY."
        ),
    ),
) -> dict[str, Any]:
    """Return a digest of Celery workers and broker queue backlogs.

    Probes the Celery control API (ping, stats, active, reserved, scheduled,
    active_queues) plus the Redis broker's ``LLEN`` per queue. Every probe
    is individually guarded, so a broker outage degrades the digest instead
    of failing it, and no broker URL / credentials are ever echoed back —
    only scheme and database index.
    """
    inspect = celery_app.control.inspect(timeout=2.0)
    snapshot = worker_health_module.collect_worker_snapshot(
        inspect=inspect,
        broker_client=worker_health_module.get_broker_client(),
    )
    worker_health_module.record_worker_gauges(snapshot)
    return worker_health_module.build_worker_health(
        **snapshot,
        backlog_threshold=backlog_threshold,
        generated_at=datetime.now(UTC).isoformat(),
    )
