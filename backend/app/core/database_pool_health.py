"""Database connection-pool health digest builder and live collector.

``GET /api/v1/system/database-pool-health`` turns the SQLAlchemy
connection pool plus a cheap PostgreSQL server-side probe into an
observability digest: how many connections are checked out vs available,
overflow usage, pool utilization against ``pool_size + max_overflow``,
server connection count vs ``max_connections``, and a HEALTHY / WATCH /
DEGRADED / NO_DATA / ERROR verdict.

The digest builder is pure-Python (no SQL, no I/O) so it is verifiable
without a live database. The collectors wrap the pool and server probes
defensively: a broken pool reports ERROR, and a non-PostgreSQL database
or a restricted ``pg_stat_activity`` view degrades the server section to
``unavailable`` instead of failing the whole digest.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.metrics import metrics
from app.core.safe_errors import safe_error_label

logger = logging.getLogger(__name__)

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_NO_DATA: str = "NO_DATA"
VERDICT_ERROR: str = "ERROR"

POOL_STATUS_OK: str = "ok"
POOL_STATUS_UNAVAILABLE: str = "unavailable"
POOL_STATUS_ERROR: str = "error"

SERVER_STATUS_OK: str = "ok"
SERVER_STATUS_UNAVAILABLE: str = "unavailable"
SERVER_STATUS_ERROR: str = "error"

REASON_POOL_UTILIZATION_HIGH: str = "pool_utilization_high"
REASON_POOL_NEARLY_EXHAUSTED: str = "pool_nearly_exhausted"
REASON_POOL_PROBE_ERROR: str = "pool_probe_error"
REASON_SERVER_CONNECTIONS_HIGH: str = "server_connections_high"
REASON_SERVER_NEARLY_EXHAUSTED: str = "server_connections_nearly_exhausted"
REASON_SERVER_PROBE_ERROR: str = "server_probe_error"

# Utilization / connection-ratio thresholds. A pool at 80% capacity is a
# warning (headroom is shrinking); at 95% it is effectively exhausted.
POOL_WATCH_UTILIZATION: float = 0.80
POOL_DEGRADED_UTILIZATION: float = 0.95
SERVER_WATCH_RATIO: float = 0.80
SERVER_DEGRADED_RATIO: float = 0.95

# One query returns both sides of the server probe: how many connections
# are currently open on this database vs the server-wide cap. Using
# ``current_database()`` keeps the count scoped to the app's own database
# (the interesting number for a single-service deployment).
_SERVER_PROBE_SQL = text(
    """
    SELECT
        (SELECT COUNT(*)::int
           FROM pg_stat_activity
          WHERE datname = current_database()) AS active_connections,
        current_setting('max_connections')::int AS max_connections
    """
)


def _is_postgresql_url(database_url: str) -> bool:
    """Whether a SQLAlchemy database URL targets PostgreSQL.

    SQLAlchemy accepts both ``postgres://`` and ``postgresql://`` as
    aliases, and either may carry a driver suffix such as
    ``postgresql+psycopg``. The probe is PostgreSQL-specific, so all of
    those forms must be recognized or a perfectly healthy PostgreSQL
    deployment would silently report ``unavailable``.
    """
    url = (database_url or "").strip().lower()
    scheme = url.split("://", 1)[0]
    dialect = scheme.split("+", 1)[0]
    return dialect in {"postgres", "postgresql"}


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative int, or ``default`` when unusable."""
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


def _safe_float(value: Any) -> float | None:
    """Coerce a value to a finite non-negative float, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0:
        return None
    return parsed


def _callable_value(raw: Any) -> Any:
    """Call ``raw`` if it is callable, otherwise return it unchanged."""
    if callable(raw):
        return raw()
    return raw


def _queue_size(queue: Any) -> int | None:
    """Return the number of checked-in connections in SQLAlchemy's queue."""
    qsize = getattr(queue, "qsize", None)
    if callable(qsize):
        try:
            return _safe_optional_int(qsize())
        except Exception:
            return None
    return None


def _queue_maxsize(queue: Any) -> int | None:
    """Return the pool's base size from the internal bounded queue."""
    maxsize = getattr(queue, "maxsize", None)
    if maxsize is None:
        return None
    return _safe_optional_int(maxsize)


def collect_pool_snapshot(engine: Any) -> dict[str, Any]:
    """Collect the SQLAlchemy pool section of the digest.

    Args:
        engine: A SQLAlchemy ``Engine`` (or any object exposing
            ``pool`` with ``checkedout`` / ``overflow`` / ``timeout``).

    Returns:
        Dict with ``status`` (``ok`` / ``unavailable`` / ``error``),
        ``pool_class``, ``pool_size``, ``max_overflow``, ``checkedout``,
        ``checkedin``, ``overflow``, ``total_capacity``, ``utilization``,
        ``pool_timeout_seconds``, ``pool_recycle_seconds``, ``pre_ping``
        and an optional ``error`` string.
    """
    pool = getattr(engine, "pool", None)
    if pool is None:
        return {
            "status": POOL_STATUS_UNAVAILABLE,
            "pool_class": "",
            "error": "engine has no SQLAlchemy pool",
        }

    try:
        checkedout_raw = _callable_value(getattr(pool, "checkedout", None))
        overflow_raw = _callable_value(getattr(pool, "overflow", None))
        timeout_raw = _callable_value(getattr(pool, "timeout", None))

        checkedout = _safe_int(checkedout_raw)
        checkedin = _queue_size(getattr(pool, "_pool", None))
        pool_size = _queue_maxsize(getattr(pool, "_pool", None))
        max_overflow = _safe_optional_int(
            getattr(pool, "_max_overflow", None)
        )
        # ``overflow()`` can report a negative count before the pool fills;
        # the digest exposes only the current number of overflow
        # connections in use.
        overflow = max(0, _safe_int(overflow_raw))

        total_capacity = (pool_size or 0) + (max_overflow or 0)
        utilization = (
            min(1.0, checkedout / total_capacity)
            if total_capacity > 0
            else None
        )

        return {
            "status": POOL_STATUS_OK,
            "pool_class": type(pool).__name__,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "checkedout": checkedout,
            "checkedin": checkedin,
            "overflow": overflow,
            "total_capacity": total_capacity,
            "utilization": utilization,
            "pool_timeout_seconds": _safe_optional_int(timeout_raw),
            "pool_recycle_seconds": _safe_optional_int(
                getattr(pool, "_recycle", None)
            ),
            "pre_ping": bool(getattr(pool, "_pre_ping", False)),
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("database-pool-health pool probe failed: %s", exc)
        return {
            "status": POOL_STATUS_ERROR,
            "pool_class": type(pool).__name__,
            # Full detail is logged above; clients get the class name only.
            "error": safe_error_label(exc),
        }


def collect_server_snapshot(
    db: Any,
    database_url: str,
) -> dict[str, Any]:
    """Collect the PostgreSQL server section of the digest.

    Args:
        db: SQLAlchemy ``Session`` (or an object with ``execute``).
        database_url: The engine's URL; non-PostgreSQL URLs skip the
            probe and report ``unavailable``.

    Returns:
        Dict with ``status`` (``ok`` / ``unavailable`` / ``error``),
        ``active_connections``, ``max_connections``, ``connection_ratio``,
        ``latency_ms``, an optional ``reason`` and an optional ``error``.
    """
    if not _is_postgresql_url(database_url):
        return {
            "status": SERVER_STATUS_UNAVAILABLE,
            "reason": "non_postgresql",
            "active_connections": None,
            "max_connections": None,
            "connection_ratio": None,
            "latency_ms": None,
            "error": None,
        }

    started = time.perf_counter()
    try:
        result = db.execute(_SERVER_PROBE_SQL)
        row = (
            result.fetchone()
            if hasattr(result, "fetchone")
            else result.first()
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        if row is None:
            return {
                "status": SERVER_STATUS_ERROR,
                "reason": "empty_probe_result",
                "active_connections": None,
                "max_connections": None,
                "connection_ratio": None,
                "latency_ms": round(max(0.0, latency_ms), 3),
                "error": "server probe returned no rows",
            }
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        active = _safe_optional_int(mapping.get("active_connections"))
        maximum = _safe_optional_int(mapping.get("max_connections"))
        ratio = min(1.0, active / maximum) if maximum > 0 else None
        return {
            "status": SERVER_STATUS_OK,
            "reason": None,
            "active_connections": active,
            "max_connections": maximum,
            "connection_ratio": ratio,
            "latency_ms": round(max(0.0, latency_ms), 3),
            "error": None,
        }
    except Exception as exc:
        logger.warning("database-pool-health server probe failed: %s", exc)
        return {
            "status": SERVER_STATUS_ERROR,
            "reason": "probe_exception",
            "active_connections": None,
            "max_connections": None,
            "connection_ratio": None,
            "latency_ms": None,
            # Full detail is logged above; clients get the class name only —
            # psycopg messages can embed SQL fragments and host names.
            "error": safe_error_label(exc),
        }


def build_database_pool_health(
    *,
    pool: dict[str, Any] | None = None,
    server: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the database-pool health digest.

    Args:
        pool: The pool section from :func:`collect_pool_snapshot`.
        server: The server section from :func:`collect_server_snapshot`.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``DatabasePoolHealthOut`` schema: verdict,
        reasons, pool stats and server stats.
    """
    pool = pool or {"status": POOL_STATUS_UNAVAILABLE}
    server = server or {"status": SERVER_STATUS_UNAVAILABLE}

    pool_status = str(pool.get("status") or POOL_STATUS_UNAVAILABLE).lower()
    server_status = str(
        server.get("status") or SERVER_STATUS_UNAVAILABLE
    ).lower()
    utilization = _safe_float(pool.get("utilization"))
    connection_ratio = _safe_float(server.get("connection_ratio"))

    reasons: list[str] = []
    if pool_status == POOL_STATUS_ERROR:
        reasons.append(REASON_POOL_PROBE_ERROR)
    if server_status == SERVER_STATUS_ERROR:
        reasons.append(REASON_SERVER_PROBE_ERROR)
    if utilization is not None:
        if utilization >= POOL_DEGRADED_UTILIZATION:
            reasons.append(REASON_POOL_NEARLY_EXHAUSTED)
        elif utilization >= POOL_WATCH_UTILIZATION:
            reasons.append(REASON_POOL_UTILIZATION_HIGH)
    if connection_ratio is not None:
        if connection_ratio >= SERVER_DEGRADED_RATIO:
            reasons.append(REASON_SERVER_NEARLY_EXHAUSTED)
        elif connection_ratio >= SERVER_WATCH_RATIO:
            reasons.append(REASON_SERVER_CONNECTIONS_HIGH)

    if pool_status == POOL_STATUS_ERROR or server_status == SERVER_STATUS_ERROR:
        verdict = VERDICT_ERROR
    elif utilization is None and connection_ratio is None:
        verdict = VERDICT_NO_DATA
    elif (
        (utilization is not None and utilization >= POOL_DEGRADED_UTILIZATION)
        or (
            connection_ratio is not None
            and connection_ratio >= SERVER_DEGRADED_RATIO
        )
    ):
        verdict = VERDICT_DEGRADED
    elif (
        (utilization is not None and utilization >= POOL_WATCH_UTILIZATION)
        or (
            connection_ratio is not None
            and connection_ratio >= SERVER_WATCH_RATIO
        )
    ):
        verdict = VERDICT_WATCH
    else:
        verdict = VERDICT_HEALTHY

    checkedout = _safe_int(pool.get("checkedout"))
    total_capacity = _safe_int(pool.get("total_capacity"))
    active = _safe_int(server.get("active_connections"))
    maximum = _safe_int(server.get("max_connections"))

    if verdict == VERDICT_ERROR:
        summary = "Database connection probes are failing"
    elif total_capacity > 0 and maximum > 0:
        summary = (
            f"{checkedout}/{total_capacity} pool connections in use, "
            f"server {active}/{maximum}"
        )
    elif total_capacity > 0:
        summary = f"{checkedout}/{total_capacity} pool connections in use"
    elif maximum > 0:
        summary = f"server {active}/{maximum} connections"
    else:
        summary = "Database pool unavailable"

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "reasons": reasons,
        "summary": summary,
        "pool": {
            "status": pool_status,
            "pool_class": str(pool.get("pool_class") or ""),
            "pool_size": pool.get("pool_size"),
            "max_overflow": pool.get("max_overflow"),
            "checkedout": checkedout,
            "checkedin": pool.get("checkedin"),
            "overflow": pool.get("overflow"),
            "total_capacity": total_capacity,
            "utilization": utilization,
            "pool_timeout_seconds": pool.get("pool_timeout_seconds"),
            "pool_recycle_seconds": pool.get("pool_recycle_seconds"),
            "pre_ping": bool(pool.get("pre_ping")),
            "error": pool.get("error"),
        },
        "server": {
            "status": server_status,
            "reason": server.get("reason"),
            "active_connections": active,
            "max_connections": maximum,
            "connection_ratio": connection_ratio,
            "latency_ms": server.get("latency_ms"),
            "error": server.get("error"),
        },
    }


def record_pool_gauges(
    pool: dict[str, Any],
    server: dict[str, Any],
) -> None:
    """Mirror the digest's live numbers into Prometheus gauges.

    Skipped fields stay unset (never zeroed) so an absent probe does not
    masquerade as "0 connections". The existing ``thecee_db_pool_checked_out``
    gauge is updated here too, keeping the digest and ``/metrics`` in
    agreement.
    """
    checkedout = pool.get("checkedout")
    if checkedout is not None:
        metrics.set_db_pool_checked_out(_safe_int(checkedout))
    checkedin = pool.get("checkedin")
    if checkedin is not None:
        metrics.set_db_pool_checkedin(_safe_int(checkedin))
    overflow = pool.get("overflow")
    if overflow is not None:
        metrics.set_db_pool_overflow(_safe_int(overflow))
    utilization = _safe_float(pool.get("utilization"))
    if utilization is not None:
        metrics.set_db_pool_utilization(utilization)

    active = server.get("active_connections")
    maximum = server.get("max_connections")
    if active is not None:
        metrics.set_db_server_connections(_safe_int(active))
    if maximum is not None:
        metrics.set_db_server_max_connections(_safe_int(maximum))
    connection_ratio = _safe_float(server.get("connection_ratio"))
    if connection_ratio is not None:
        metrics.set_db_server_connection_ratio(connection_ratio)


__all__ = [
    "POOL_DEGRADED_UTILIZATION",
    "POOL_STATUS_ERROR",
    "POOL_STATUS_OK",
    "POOL_STATUS_UNAVAILABLE",
    "POOL_WATCH_UTILIZATION",
    "REASON_POOL_NEARLY_EXHAUSTED",
    "REASON_POOL_PROBE_ERROR",
    "REASON_POOL_UTILIZATION_HIGH",
    "REASON_SERVER_CONNECTIONS_HIGH",
    "REASON_SERVER_NEARLY_EXHAUSTED",
    "REASON_SERVER_PROBE_ERROR",
    "SERVER_DEGRADED_RATIO",
    "SERVER_STATUS_ERROR",
    "SERVER_STATUS_OK",
    "SERVER_STATUS_UNAVAILABLE",
    "SERVER_WATCH_RATIO",
    "VERDICT_DEGRADED",
    "VERDICT_ERROR",
    "VERDICT_HEALTHY",
    "VERDICT_NO_DATA",
    "VERDICT_WATCH",
    "build_database_pool_health",
    "collect_pool_snapshot",
    "collect_server_snapshot",
    "record_pool_gauges",
]
