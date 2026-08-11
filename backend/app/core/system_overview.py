"""One-call system status overview across the health digests.

Each subsystem health digest (request, query, database pool, LLM, cache,
worker, simulation, websocket) already exists as its own endpoint. This
module composes them into a single lightweight dashboard payload:
per-subsystem verdicts and headline metrics, plus the database / Redis /
Celery service probes, so a monitoring dashboard can poll one URL instead
of eight.

The composition is pure Python (no I/O): callers build the individual
digests and service probes, then pass them in. ``NO_DATA`` and
``UNCONFIGURED`` verdicts count as healthy (nothing is broken, there is
just no signal yet); ``WATCH`` / ``DEGRADED`` / ``ERROR`` mark the overall
status degraded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_NO_DATA: str = "NO_DATA"
VERDICT_UNCONFIGURED: str = "UNCONFIGURED"
VERDICT_ERROR: str = "ERROR"

# Verdicts that mean "nothing is broken". NO_DATA / UNCONFIGURED are
# healthy because there is no traffic to judge yet, not because a probe
# failed.
_HEALTHY_VERDICTS: frozenset[str] = frozenset(
    {
        VERDICT_HEALTHY,
        VERDICT_NO_DATA,
        VERDICT_UNCONFIGURED,
    }
)

# The request-health digest does not currently emit its own verdict, so
# the overview derives one from the overall error rate. These thresholds
# mirror the style of the other digests: a small tolerated error band,
# then WATCH, then DEGRADED.
REQUEST_WATCH_ERROR_RATE: float = 0.01
REQUEST_DEGRADED_ERROR_RATE: float = 0.10

_SUBSYSTEM_ORDER: tuple[tuple[str, str], ...] = (
    ("request", "HTTP requests"),
    ("query", "Database queries"),
    ("pool", "Database pool"),
    ("llm", "LLM calls"),
    ("cache", "Response cache"),
    ("worker", "Celery workers"),
    ("simulation", "Simulations"),
    ("websocket", "Live progress delivery"),
)


def _safe_int(value: Any) -> int:
    """Coerce a value to a non-negative int, or ``0`` when unusable."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed > 0 else 0


def _safe_float(value: Any) -> float | None:
    """Coerce a value to a finite float, or ``None`` when unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _verdict_healthy(verdict: str) -> bool:
    """Whether a digest verdict means the subsystem is currently healthy."""
    return str(verdict).upper() in _HEALTHY_VERDICTS


def _request_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    total_requests = _safe_int(digest.get("total_requests"))
    error_rate = _safe_float(digest.get("overall_error_rate"))
    route_count = _safe_int(digest.get("route_count"))

    if total_requests <= 0:
        verdict = VERDICT_NO_DATA
        summary = "No HTTP request traffic recorded yet"
    else:
        if error_rate is not None and error_rate > REQUEST_DEGRADED_ERROR_RATE:
            verdict = VERDICT_DEGRADED
        elif error_rate is not None and error_rate > REQUEST_WATCH_ERROR_RATE:
            verdict = VERDICT_WATCH
        else:
            verdict = VERDICT_HEALTHY
        rate_text = (
            f"{error_rate:.1%} error rate"
            if error_rate is not None
            else "no errors recorded"
        )
        summary = f"{total_requests} request(s), {rate_text}"

    return {
        "key": "request",
        "label": "HTTP requests",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "total_requests": total_requests,
            "error_rate": error_rate,
            "route_count": route_count,
        },
    }


def _query_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    total_queries = _safe_int(digest.get("total_queries"))
    error_rate = _safe_float(digest.get("error_rate"))
    slow_query_count = _safe_int(digest.get("slow_query_count"))
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()

    if total_queries <= 0:
        summary = "No SQL query traffic recorded yet"
    else:
        rate_text = (
            f"{error_rate:.1%} error rate"
            if error_rate is not None
            else "no errors recorded"
        )
        summary = (
            f"{total_queries} queries, {rate_text}, "
            f"{slow_query_count} slow"
        )

    return {
        "key": "query",
        "label": "Database queries",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "total_queries": total_queries,
            "error_rate": error_rate,
            "slow_query_count": slow_query_count,
        },
    }


def _pool_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    pool = digest.get("pool") or {}
    server = digest.get("server") or {}
    checkedout = _safe_int(pool.get("checkedout"))
    total_capacity = _safe_int(pool.get("total_capacity"))
    utilization = _safe_float(pool.get("utilization"))
    active = _safe_int(server.get("active_connections"))
    maximum = _safe_int(server.get("max_connections"))
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()

    if total_capacity > 0 and maximum > 0:
        summary = (
            f"{checkedout}/{total_capacity} connections in use, "
            f"server {active}/{maximum}"
        )
    elif total_capacity > 0:
        summary = f"{checkedout}/{total_capacity} connections in use"
    elif maximum > 0:
        summary = f"server {active}/{maximum} connections"
    elif verdict == VERDICT_ERROR:
        summary = "Database connection probes are failing"
    else:
        summary = "Database pool unavailable"

    return {
        "key": "pool",
        "label": "Database pool",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "checkedout": checkedout,
            "total_capacity": total_capacity,
            "utilization": utilization,
            "active_connections": active,
            "max_connections": maximum,
            "connection_ratio": _safe_float(server.get("connection_ratio")),
        },
    }


def _llm_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    total_attempts = _safe_int(digest.get("total_attempts"))
    success_rate = _safe_float(digest.get("success_rate"))
    failure_count = _safe_int(digest.get("failure_count"))
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()

    if total_attempts <= 0:
        summary = "No LLM calls recorded yet"
    else:
        success_text = (
            f"{success_rate:.1%} success"
            if success_rate is not None
            else "no successes recorded"
        )
        summary = f"{total_attempts} attempt(s), {success_text}"

    return {
        "key": "llm",
        "label": "LLM calls",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "total_attempts": total_attempts,
            "success_rate": success_rate,
            "failure_count": failure_count,
        },
    }


def _cache_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    total_reads = _safe_int(digest.get("total_reads"))
    hit_rate = _safe_float(digest.get("hit_rate"))
    current_keys = digest.get("current_keys")
    current_keys_safe: int | None = (
        _safe_int(current_keys) if current_keys is not None else None
    )
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()

    if verdict == VERDICT_UNCONFIGURED:
        summary = "Response cache unconfigured (no Redis client)"
    elif total_reads <= 0:
        summary = "No response-cache traffic recorded yet"
    else:
        hit_text = (
            f"{hit_rate:.1%} hit rate"
            if hit_rate is not None
            else "no hits recorded"
        )
        summary = f"{hit_text} over {total_reads} read(s)"

    return {
        "key": "cache",
        "label": "Response cache",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "total_reads": total_reads,
            "hit_rate": hit_rate,
            "current_keys": current_keys_safe,
        },
    }


def _worker_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    totals = digest.get("totals") or {}
    broker = digest.get("broker") or {}
    workers_online = _safe_int(totals.get("workers_online"))
    queue_depth = _safe_int(totals.get("queue_depth"))
    active_tasks = _safe_int(totals.get("active_tasks"))
    broker_status = str(broker.get("status") or "unconfigured").lower()
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()
    reasons = [str(reason) for reason in digest.get("reasons") or []]

    if broker_status in {"unconfigured", "unsupported"}:
        summary = "Celery broker unconfigured or unsupported"
    elif workers_online <= 0:
        summary = "No Celery workers online"
    else:
        summary = (
            f"{workers_online} worker(s), {queue_depth} queued, "
            f"{active_tasks} active"
        )

    return {
        "key": "worker",
        "label": "Celery workers",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "workers_online": workers_online,
            "queue_depth": queue_depth,
            "active_tasks": active_tasks,
            "reasons": reasons,
        },
    }


def _simulation_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    total_simulations = _safe_int(digest.get("total_simulations"))
    completion_rate = _safe_float(digest.get("completion_rate"))
    failed_count = _safe_int(digest.get("failed_count"))
    verdict = str(digest.get("verdict") or VERDICT_NO_DATA).upper()
    reasons = [str(reason) for reason in digest.get("reasons") or []]

    if total_simulations <= 0:
        summary = "No simulations in the recency window"
    elif completion_rate is None:
        summary = "No terminal simulations yet"
    else:
        summary = (
            f"{completion_rate:.1%} completion over "
            f"{total_simulations} run(s)"
        )

    return {
        "key": "simulation",
        "label": "Simulations",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "total_simulations": total_simulations,
            "completion_rate": completion_rate,
            "failed_count": failed_count,
            "reasons": reasons,
        },
    }


def _websocket_subsystem(digest: dict[str, Any]) -> dict[str, Any]:
    delivery_mode = str(
        digest.get("delivery_mode") or "IN_PROCESS_FALLBACK"
    )
    connections = _safe_int(digest.get("connection_count"))
    bridge_running = bool(digest.get("bridge_running"))
    verdict = str(digest.get("verdict") or VERDICT_UNCONFIGURED).upper()
    reasons = [str(reason) for reason in digest.get("reasons") or []]

    if verdict == VERDICT_UNCONFIGURED:
        summary = "Live progress delivery unconfigured (same-process fallback)"
    elif verdict == VERDICT_DEGRADED:
        reason = reasons[0] if reasons else "delivery path is down"
        summary = f"Live progress delivery degraded: {reason}"
    elif verdict == VERDICT_WATCH:
        summary = (
            "Live progress delivery recovering after a recent publish "
            f"outage ({connections} listener(s))"
        )
    elif bridge_running and connections > 0:
        summary = f"Redis pub/sub relay live, {connections} listener(s)"
    elif bridge_running:
        summary = "Redis pub/sub relay live, no listeners connected"
    else:
        summary = "Live progress subscriber not running"

    return {
        "key": "websocket",
        "label": "Live progress delivery",
        "verdict": verdict,
        "healthy": _verdict_healthy(verdict),
        "summary": summary,
        "headline": {
            "delivery_mode": delivery_mode,
            "bridge_running": bridge_running,
            "connection_count": connections,
            "redis_reachable": digest.get("redis_reachable"),
            "reasons": reasons,
        },
    }


def _build_services(
    services: dict[str, Any],
    worker_digest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compose database / Redis probes plus the Celery worker service row.

    The Celery service row is derived from the worker digest so the
    overview does not double-probe the control API (the digest already
    pinged every worker and the broker).
    """
    database = services.get("database") or {}
    redis = services.get("redis") or {}
    rows: list[dict[str, Any]] = [
        {
            "name": "database",
            "status": str(database.get("status") or "unknown"),
            "latency_ms": _safe_float(database.get("latency_ms")),
            "detail": str(database.get("error") or ""),
        },
        {
            "name": "redis",
            "status": str(redis.get("status") or "unknown"),
            "latency_ms": _safe_float(redis.get("latency_ms")),
            "detail": str(redis.get("error") or ""),
        },
    ]

    broker = worker_digest.get("broker") or {}
    totals = worker_digest.get("totals") or {}
    broker_status = str(broker.get("status") or "unconfigured").lower()
    workers_online = _safe_int(totals.get("workers_online"))

    if broker_status == "ok":
        if workers_online > 0:
            status: str = "ok"
            detail: str = f"{workers_online} worker(s) online"
        else:
            status = "degraded"
            detail = "Broker reachable but no workers online"
    elif broker_status in {"unconfigured", "unsupported"}:
        status = "unconfigured"
        detail = "Celery broker unconfigured or unsupported"
    elif broker_status == "error":
        status = "error"
        detail = str(broker.get("error") or "Celery broker unreachable")
    else:
        status = "unknown"
        detail = "Celery worker status unknown"
    rows.append(
        {
            "name": "worker",
            "status": status,
            "latency_ms": None,
            "detail": detail,
        }
    )
    return rows


def build_system_overview(
    *,
    request: dict[str, Any],
    query: dict[str, Any],
    llm: dict[str, Any],
    cache: dict[str, Any],
    worker: dict[str, Any],
    simulation: dict[str, Any],
    pool: dict[str, Any] | None = None,
    websocket: dict[str, Any] | None = None,
    services: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the one-call system overview from the individual digests.

    Args:
        request: ``RequestHealthOut`` payload (or equivalent dict).
        query: ``QueryHealthOut`` payload.
        llm: ``LLMHealthOut`` payload.
        cache: ``CacheHealthOut`` payload.
        worker: ``WorkerHealthOut`` payload.
        simulation: ``SimulationHealthOut`` payload.
        pool: ``DatabasePoolHealthOut`` payload. Optional for backward
            compatibility; when omitted the pool row reports NO_DATA.
        websocket: ``WebsocketHealthOut`` payload. Optional for backward
            compatibility; when omitted the row reports UNCONFIGURED
            (same-process fallback, healthy).
        services: Probe results for ``database`` and ``redis`` (the
            worker service row is derived from ``worker``).
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``SystemOverviewOut`` schema: overall
        status / healthy flag, unhealthy component names, service rows
        and per-subsystem verdict / summary / headline rows.
    """
    builders: dict[str, Any] = {
        "request": _request_subsystem,
        "query": _query_subsystem,
        "pool": _pool_subsystem,
        "llm": _llm_subsystem,
        "cache": _cache_subsystem,
        "worker": _worker_subsystem,
        "simulation": _simulation_subsystem,
        "websocket": _websocket_subsystem,
    }
    digests: dict[str, dict[str, Any]] = {
        "request": request,
        "query": query,
        "pool": pool
        or {
            "verdict": VERDICT_NO_DATA,
            "reasons": [],
            "pool": {"status": "unavailable"},
            "server": {"status": "unavailable"},
        },
        "llm": llm,
        "cache": cache,
        "worker": worker,
        "simulation": simulation,
        "websocket": websocket
        or {
            "verdict": VERDICT_UNCONFIGURED,
            "delivery_mode": "IN_PROCESS_FALLBACK",
            "bridge_running": False,
            "connection_count": 0,
            "redis_reachable": None,
        },
    }

    subsystems: list[dict[str, Any]] = []
    for key, _label in _SUBSYSTEM_ORDER:
        subsystems.append(builders[key](digests[key]))

    service_rows = _build_services(services, worker)

    subsystem_healthy = all(row["healthy"] for row in subsystems)
    services_healthy = all(
        row["status"] in {"ok", "unconfigured"} for row in service_rows
    )
    healthy = bool(subsystem_healthy and services_healthy)

    unhealthy_components: list[str] = [
        row["key"] for row in subsystems if not row["healthy"]
    ]
    unhealthy_components.extend(
        row["name"]
        for row in service_rows
        if row["status"] not in {"ok", "unconfigured"}
    )

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "status": "ok" if healthy else "degraded",
        "healthy": healthy,
        "unhealthy_components": unhealthy_components,
        "services": service_rows,
        "subsystems": subsystems,
    }


__all__ = [
    "REQUEST_DEGRADED_ERROR_RATE",
    "REQUEST_WATCH_ERROR_RATE",
    "VERDICT_DEGRADED",
    "VERDICT_HEALTHY",
    "VERDICT_NO_DATA",
    "VERDICT_UNCONFIGURED",
    "VERDICT_WATCH",
    "build_system_overview",
]
