"""Celery worker and queue health digest builder and live collector.

``/system/health`` probes Celery liveness (ping + worker count); this
module turns a full Celery inspection into an observability digest:
per-worker concurrency / pid / prefetch / uptime / in-flight task counts,
per-queue broker depth (Redis ``LLEN``) plus active / reserved / scheduled
task counts attributed by routing key, aggregate totals, and a HEALTHY /
WATCH / DEGRADED / NO_DATA verdict.

The digest builder is pure-Python (no Celery, no Redis, no I/O) so it is
verifiable without a running worker. The collector wraps the Celery
``Inspect`` API and an optional Redis broker client defensively: every
probe is individually guarded, so a partial outage degrades the affected
section instead of failing the whole digest.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import redis

from app.core.config import settings
from app.core.metrics import metrics
from app.core.safe_errors import safe_error_label

logger = logging.getLogger(__name__)

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_NO_DATA: str = "NO_DATA"

REASON_BROKER_UNREACHABLE: str = "broker_unreachable"
REASON_NO_WORKERS: str = "no_workers"
REASON_QUEUE_BACKLOG: str = "queue_backlog"
REASON_BROKER_DEPTH_UNAVAILABLE: str = "broker_depth_unavailable"

DEFAULT_BACKLOG_THRESHOLD: int = 200
MAX_BACKLOG_THRESHOLD: int = 10_000
DEFAULT_QUEUE: str = "celery"

_BROKER_STATUS_OK: str = "ok"
_BROKER_STATUS_ERROR: str = "error"
_BROKER_STATUS_UNCONFIGURED: str = "unconfigured"
_BROKER_STATUS_UNSUPPORTED: str = "unsupported"


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _safe_optional_int(value: Any) -> int | None:
    """Coerce a value to a non-negative int, or ``None`` when absent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _task_counts_by_queue(
    tasks_by_host: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """Count in-flight task dicts by their ``delivery_info.routing_key``."""
    counts: dict[str, int] = {}
    for tasks in tasks_by_host.values():
        for task in tasks:
            if not isinstance(task, dict):
                continue
            delivery_info = task.get("delivery_info")
            if not isinstance(delivery_info, dict):
                # Scheduled tasks wrap the request (with delivery_info)
                # under a ``request`` key instead of at the top level.
                request = task.get("request")
                if isinstance(request, dict):
                    delivery_info = request.get("delivery_info")
            queue = DEFAULT_QUEUE
            if isinstance(delivery_info, dict):
                routing_key = str(
                    delivery_info.get("routing_key") or DEFAULT_QUEUE
                ).strip()
                queue = routing_key or DEFAULT_QUEUE
            counts[queue] = counts.get(queue, 0) + 1
    return counts


def _broker_metadata() -> dict[str, Any]:
    """Expose only safe broker metadata (never credentials or hosts)."""
    url = settings.CELERY_BROKER_URL or ""
    scheme = url.split("://", 1)[0] if "://" in url else ""
    database: int | None = None
    if scheme in {"redis", "rediss"}:
        tail = url.rsplit("/", 1)[-1]
        if tail.isdigit():
            database = int(tail)
    return {"scheme": scheme, "database": database}


def get_broker_client() -> redis.Redis | None:
    """Build a Redis client for the Celery broker, or ``None`` when unusable.

    Only Redis / Redis-SSL brokers support cheap ``LLEN`` queue-depth
    probing; other broker transports return ``None`` and the digest
    reports depth as unavailable rather than failing.
    """
    url = (settings.CELERY_BROKER_URL or "").strip()
    if not url or not url.startswith(("redis://", "rediss://")):
        return None
    try:
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("worker-health: broker client init failed: %s", exc)
        return None


def _probe_task_map(
    inspect: Any,
    method: str,
) -> dict[str, list[dict[str, Any]]]:
    """Call one Celery inspect method, tolerating a failed probe."""
    try:
        result = getattr(inspect, method)() or {}
        cleaned: dict[str, list[dict[str, Any]]] = {}
        for host, tasks in result.items():
            if isinstance(tasks, list):
                cleaned[str(host)] = tasks
            elif isinstance(tasks, dict):
                # Some brokers return a dict wrapper; keep the list value.
                for value in tasks.values():
                    if isinstance(value, list):
                        cleaned[str(host)] = value
                        break
        return cleaned
    except Exception as exc:
        logger.warning("worker-health: inspect.%s() failed: %s", method, exc)
        return {}


def _probe_stats(
    inspect: Any,
) -> dict[str, dict[str, Any]]:
    """Call ``inspect.stats()``, tolerating a failed probe."""
    try:
        result = inspect.stats() or {}
        return {
            str(host): value
            for host, value in result.items()
            if isinstance(value, dict)
        }
    except Exception as exc:
        logger.warning("worker-health: inspect.stats() failed: %s", exc)
        return {}


def _probe_active_queues(
    inspect: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Call ``inspect.active_queues()``, tolerating a failed probe."""
    try:
        result = inspect.active_queues() or {}
        cleaned: dict[str, list[dict[str, Any]]] = {}
        for host, queues in result.items():
            if isinstance(queues, list):
                cleaned[str(host)] = queues
        return cleaned
    except Exception as exc:
        logger.warning("worker-health: inspect.active_queues() failed: %s", exc)
        return {}


def _probe_broker(
    broker_client: redis.Redis | None,
) -> dict[str, Any]:
    """Ping the broker client and return a safe status dict."""
    metadata = _broker_metadata()
    if broker_client is None:
        if metadata["scheme"] in {"redis", "rediss"}:
            # A Redis transport is configured but no client could be
            # built; the probe is unavailable rather than unsupported.
            return {
                "status": _BROKER_STATUS_UNCONFIGURED,
                **metadata,
            }
        return {
            "status": (
                _BROKER_STATUS_UNSUPPORTED
                if metadata["scheme"]
                else _BROKER_STATUS_UNCONFIGURED
            ),
            **metadata,
        }
    try:
        broker_client.ping()
    except Exception as exc:
        logger.warning("worker-health: broker ping failed: %s", exc)
        return {
            "status": _BROKER_STATUS_ERROR,
            **metadata,
            # Full detail is logged above; clients get the class name only —
            # broker messages can embed endpoints and credentials.
            "error": safe_error_label(exc),
        }
    return {"status": _BROKER_STATUS_OK, **metadata}


def _queue_depths(
    queue_names: list[str],
    broker_status: str,
    broker_client: redis.Redis | None,
) -> dict[str, int | None]:
    """Measure Redis broker depth per queue; ``None`` when unavailable."""
    if broker_status != _BROKER_STATUS_OK or broker_client is None:
        return {name: None for name in queue_names}
    depths: dict[str, int | None] = {}
    for name in queue_names:
        try:
            value = broker_client.llen(name)
            depths[name] = _safe_int(value)
        except Exception as exc:
            logger.warning(
                "worker-health: LLEN %r failed: %s",
                name,
                exc,
            )
            depths[name] = None
    return depths


def collect_worker_snapshot(
    *,
    inspect: Any,
    broker_client: redis.Redis | None,
) -> dict[str, Any]:
    """Probe a Celery ``Inspect`` and optional Redis broker client.

    Returns a snapshot dict ready for ``build_worker_health``. Every probe
    is individually guarded: a broker outage still yields worker rows when
    the workers respond, and an inspect failure still yields broker status.
    """
    try:
        pong = inspect.ping() or {}
        worker_hostnames = sorted(str(host) for host in pong)
    except Exception as exc:
        logger.warning("worker-health: Celery ping failed: %s", exc)
        worker_hostnames = []

    active_tasks = _probe_task_map(inspect, "active")
    reserved_tasks = _probe_task_map(inspect, "reserved")
    scheduled_tasks = _probe_task_map(inspect, "scheduled")
    worker_stats = _probe_stats(inspect)
    active_queues = _probe_active_queues(inspect)
    broker = _probe_broker(broker_client)

    active_by_queue = _task_counts_by_queue(active_tasks)
    reserved_by_queue = _task_counts_by_queue(reserved_tasks)
    scheduled_by_queue = _task_counts_by_queue(scheduled_tasks)

    queue_names: list[str] = []
    for queues in active_queues.values():
        for queue in queues:
            if not isinstance(queue, dict):
                continue
            name = str(queue.get("name") or "").strip()
            if name and name not in queue_names:
                queue_names.append(name)
    # ``active_queues`` is one of the more fragile control-command probes.
    # When it fails, recover queue names from the routing keys of in-flight
    # active / reserved / scheduled tasks so per-queue depth is still
    # measured for the queues that actually have work.
    task_queue_names: set[str] = set()
    task_queue_names.update(active_by_queue)
    task_queue_names.update(reserved_by_queue)
    task_queue_names.update(scheduled_by_queue)
    queue_names = sorted(set(queue_names) | task_queue_names)
    if not queue_names:
        queue_names = [DEFAULT_QUEUE]

    depth_by_queue = _queue_depths(
        queue_names,
        broker["status"],
        broker_client,
    )

    workers: list[dict[str, Any]] = []
    for hostname in worker_hostnames:
        stats = worker_stats.get(hostname, {})
        pool = stats.get("pool") if isinstance(stats, dict) else None
        concurrency = (
            _safe_optional_int(pool.get("max-concurrency"))
            if isinstance(pool, dict)
            else None
        )
        if concurrency is not None and concurrency < 1:
            # A zero/negative concurrency is never valid; ``None`` keeps
            # the digest schema-valid instead of 500ing the response.
            concurrency = None
        workers.append(
            {
                "hostname": hostname,
                "concurrency": concurrency,
                "pid": _safe_optional_int(stats.get("pid")),
                "prefetch_count": _safe_optional_int(
                    stats.get("prefetch_count")
                ),
                "uptime_seconds": _safe_optional_int(stats.get("uptime")),
                "active_tasks": len(active_tasks.get(hostname) or []),
                "reserved_tasks": len(reserved_tasks.get(hostname) or []),
                "scheduled_tasks": len(scheduled_tasks.get(hostname) or []),
            }
        )

    queues: list[dict[str, Any]] = []
    for name in queue_names:
        queues.append(
            {
                "name": name,
                "depth": depth_by_queue.get(name),
                "active_tasks": active_by_queue.get(name, 0),
                "reserved_tasks": reserved_by_queue.get(name, 0),
                "scheduled_tasks": scheduled_by_queue.get(name, 0),
            }
        )

    return {
        "workers_online": len(workers),
        "workers": workers,
        "queues": queues,
        "broker": broker,
    }


def _verdict_and_reasons(
    *,
    broker_status: str,
    workers_online: int,
    queue_depth: int,
    backlog_threshold: int,
) -> tuple[str, list[str]]:
    if broker_status == _BROKER_STATUS_ERROR:
        return VERDICT_DEGRADED, [REASON_BROKER_UNREACHABLE]
    if workers_online <= 0:
        if broker_status in {
            _BROKER_STATUS_UNCONFIGURED,
            _BROKER_STATUS_UNSUPPORTED,
        }:
            return VERDICT_NO_DATA, [REASON_BROKER_DEPTH_UNAVAILABLE]
        return VERDICT_DEGRADED, [REASON_NO_WORKERS]
    if (
        broker_status == _BROKER_STATUS_OK
        and queue_depth > backlog_threshold
    ):
        return VERDICT_WATCH, [REASON_QUEUE_BACKLOG]
    return VERDICT_HEALTHY, []


def build_worker_health(
    *,
    workers_online: int,
    workers: list[dict[str, Any]] | None = None,
    queues: list[dict[str, Any]] | None = None,
    broker: dict[str, Any] | None = None,
    backlog_threshold: int = DEFAULT_BACKLOG_THRESHOLD,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the worker-health digest from a collected snapshot.

    Pure and deterministic (no Celery / Redis / I/O), so the verdict
    logic is unit-testable without a running worker or broker.
    """
    workers = workers or []
    queues = queues or []
    broker = broker or {}

    workers_online_safe = _safe_int(workers_online)
    total_active = sum(_safe_int(row.get("active_tasks")) for row in workers)
    total_reserved = sum(
        _safe_int(row.get("reserved_tasks")) for row in workers
    )
    total_scheduled = sum(
        _safe_int(row.get("scheduled_tasks")) for row in workers
    )
    queue_depth = sum(
        _safe_int(row.get("depth"))
        for row in queues
        if row.get("depth") is not None
    )

    broker_status = str(broker.get("status") or _BROKER_STATUS_UNCONFIGURED)
    verdict, reasons = _verdict_and_reasons(
        broker_status=broker_status,
        workers_online=workers_online_safe,
        queue_depth=queue_depth,
        backlog_threshold=_safe_int(
            backlog_threshold,
            DEFAULT_BACKLOG_THRESHOLD,
        ),
    )

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "reasons": reasons,
        "broker": {
            "status": broker_status,
            "scheme": str(broker.get("scheme") or ""),
            "database": broker.get("database"),
            "error": broker.get("error"),
        },
        "totals": {
            "workers_online": workers_online_safe,
            "active_tasks": total_active,
            "reserved_tasks": total_reserved,
            "scheduled_tasks": total_scheduled,
            "queue_depth": queue_depth,
        },
        "workers": workers,
        "queues": queues,
    }


def record_worker_gauges(snapshot: dict[str, Any]) -> None:
    """Mirror the snapshot into Prometheus gauges for ``/metrics``."""
    workers_online = _safe_int(snapshot.get("workers_online"))
    metrics.set_celery_workers_online(workers_online)
    for queue in snapshot.get("queues") or []:
        depth = queue.get("depth")
        if depth is not None:
            metrics.set_celery_queue_depth(
                str(queue.get("name") or DEFAULT_QUEUE),
                _safe_int(depth),
            )
