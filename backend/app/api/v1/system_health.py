"""System health summary endpoint."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.redis_client import get_redis_client
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
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
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
