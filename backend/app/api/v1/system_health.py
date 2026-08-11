"""System health summary endpoint."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import database_pool_health as database_pool_health_module
from app.core import llm_health as llm_health_module
from app.core import query_health as query_health_module
from app.core import response_cache as response_cache_module
from app.core import simulation_health as simulation_health_module
from app.core import worker_health as worker_health_module
from app.core.cache_health import build_cache_health
from app.core.config import settings
from app.core.database import engine
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
from app.core.system_overview import build_system_overview
from app.schemas.system_health import (
    CacheHealthOut,
    DatabasePoolHealthOut,
    LLMHealthOut,
    QueryHealthOut,
    RequestHealthOut,
    SimulationHealthOut,
    SystemHealthOut,
    SystemOverviewOut,
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


@router.get(
    "/simulation-health",
    summary=(
        "Simulation pipeline health (completion rates, latency "
        "percentiles, failure buckets)"
    ),
    responses=_JSON_200,
    response_model=SimulationHealthOut,
)
def simulation_health(
    db: Session = Depends(get_db),
    window_days: int = Query(
        default=simulation_health_module.DEFAULT_WINDOW_DAYS,
        ge=1,
        le=simulation_health_module.MAX_WINDOW_DAYS,
        description=(
            "Number of recent days of simulation history to include in "
            "the digest."
        ),
    ),
    recent_failures_limit: int = Query(
        default=simulation_health_module.DEFAULT_RECENT_FAILURES_LIMIT,
        ge=1,
        le=simulation_health_module.MAX_RECENT_FAILURES_LIMIT,
        description="Maximum number of recent failed runs to return.",
    ),
) -> dict[str, Any]:
    """Return a digest of the simulation pipeline's recent performance.

    Reads only the ``simulations`` table bounded by ``window_days`` (never
    ``results_json``): per-status counts, completion and failure rates,
    completion-latency percentiles, coarse failure buckets spanning the
    whole window (timeout / LLM API / database / infrastructure / other /
    missing message), the most recent failures, a zero-filled daily trend,
    and a HEALTHY / WATCH / DEGRADED / NO_DATA verdict. The digest is
    database-backed, so it reflects every worker's writes rather than just
    this process's view.
    """
    snapshot = simulation_health_module.collect_simulation_snapshot(
        db,
        window_days=window_days,
    )
    return simulation_health_module.build_simulation_health(
        **snapshot,
        window_days=window_days,
        recent_failures_limit=recent_failures_limit,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/database-pool-health",
    summary=(
        "Database connection-pool health (in-use connections, "
        "utilization, server headroom)"
    ),
    responses=_JSON_200,
    response_model=DatabasePoolHealthOut,
)
def database_pool_health(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return a digest of the SQLAlchemy pool and PostgreSQL headroom.

    Reads the engine's live pool state (checked-out / checked-in
    connections, overflow, utilization against pool_size + max_overflow)
    and probes the server for active connections vs ``max_connections``.
    Every probe is individually guarded: a non-PostgreSQL database or a
    restricted ``pg_stat_activity`` view degrades the server section to
    ``unavailable`` instead of failing the digest, and a broken pool
    reports ``ERROR`` so operators can page on connection exhaustion
    before requests start timing out on ``pool_timeout``.
    """
    pool = database_pool_health_module.collect_pool_snapshot(engine)
    server = database_pool_health_module.collect_server_snapshot(
        db,
        settings.DATABASE_URL,
    )
    database_pool_health_module.record_pool_gauges(pool, server)
    return database_pool_health_module.build_database_pool_health(
        pool=pool,
        server=server,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/overview",
    summary="One-call system status overview across all health digests",
    responses=_JSON_200,
    response_model=SystemOverviewOut,
    # Probes the Celery control API, the Redis broker and key space, and
    # several tables, so bound dashboard polling the way the other
    # observability digests are bounded. Fails open so the overview is
    # still reachable when the Redis-backed limiter itself is down.
    dependencies=[
        Depends(rate_limit(limit=5, window_s=60, fail_open=True))
    ],
)
def system_overview(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return every subsystem health digest as one lightweight payload.

    Composes the request, query, LLM, response-cache, Celery worker and
    simulation digests into per-subsystem verdict / summary / headline
    rows, plus the database / Redis / Celery service probes. This is the
    single URL a dashboard can poll instead of the six individual
    ``/system/*-health`` endpoints; ``NO_DATA`` / ``UNCONFIGURED``
    verdicts count as healthy, while any ``WATCH`` / ``DEGRADED`` /
    ``ERROR`` subsystem or service marks the overall status degraded.
    It also mirrors the Celery snapshot into the same Prometheus gauges
    the standalone worker-health endpoint updates, so polling only the
    overview keeps ``/metrics`` fresh.
    """
    snapshot = metrics.snapshot()
    generated_at = datetime.now(UTC).isoformat()

    request_digest = build_request_health(
        snapshot,
        generated_at=generated_at,
    )
    query_digest = query_health_module.build_query_health(
        snapshot,
        slow_queries=slow_queries_snapshot(
            limit=query_health_module.DEFAULT_LIMIT
        ),
        generated_at=generated_at,
    )
    llm_digest = llm_health_module.build_llm_health(
        snapshot,
        generated_at=generated_at,
    )
    key_counts, redis_configured = response_cache_module.current_key_counts()
    cache_digest = build_cache_health(
        snapshot,
        key_counts=key_counts,
        redis_configured=redis_configured,
        generated_at=generated_at,
    )

    inspect = celery_app.control.inspect(timeout=2.0)
    worker_snapshot = worker_health_module.collect_worker_snapshot(
        inspect=inspect,
        broker_client=worker_health_module.get_broker_client(),
    )
    worker_health_module.record_worker_gauges(worker_snapshot)
    worker_digest = worker_health_module.build_worker_health(
        **worker_snapshot,
        backlog_threshold=worker_health_module.DEFAULT_BACKLOG_THRESHOLD,
        generated_at=generated_at,
    )

    simulation_snapshot = simulation_health_module.collect_simulation_snapshot(
        db,
        window_days=simulation_health_module.DEFAULT_WINDOW_DAYS,
    )
    simulation_digest = simulation_health_module.build_simulation_health(
        **simulation_snapshot,
        window_days=simulation_health_module.DEFAULT_WINDOW_DAYS,
        recent_failures_limit=(
            simulation_health_module.DEFAULT_RECENT_FAILURES_LIMIT
        ),
        generated_at=generated_at,
    )

    pool_snapshot = database_pool_health_module.collect_pool_snapshot(engine)
    server_snapshot = database_pool_health_module.collect_server_snapshot(
        db,
        settings.DATABASE_URL,
    )
    database_pool_health_module.record_pool_gauges(
        pool_snapshot,
        server_snapshot,
    )
    pool_digest = database_pool_health_module.build_database_pool_health(
        pool=pool_snapshot,
        server=server_snapshot,
        generated_at=generated_at,
    )

    return build_system_overview(
        request=request_digest,
        query=query_digest,
        llm=llm_digest,
        cache=cache_digest,
        worker=worker_digest,
        simulation=simulation_digest,
        pool=pool_digest,
        services={
            "database": _db_status(db),
            "redis": _redis_status(),
        },
        generated_at=generated_at,
    )
