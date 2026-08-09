import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.audit_middleware import AuditLogMiddleware
from app.core.config import settings
from app.core.database import engine, init_extensions
from app.core.errors import TheCeeError, generic_error_handler, thecee_error_handler
from app.core.logging_config import configure_logging
from app.core.metrics import metrics
from app.core.progress_bridge import progress_bridge
from app.core.redis_client import get_redis_client
from app.core.request_id_middleware import RequestIdMiddleware
from app.core.timing_middleware import TimingMiddleware
from app.worker import celery_app as _celery_app

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_extensions()
    logger.info("TheCee backend running — pgvector enabled")
    # Live progress relay: subscribes this process to the Redis progress
    # channel so WebSocket clients receive Celery-task progress even though
    # the worker runs in a separate process. No-op-safe when Redis is down.
    await progress_bridge.ensure_running()

    from app.core.database import SessionLocal
    from app.simulation.clusters.registry import ClusterRegistry
    db = SessionLocal()
    try:
        ClusterRegistry().sync_to_db(db)
        logger.info("Cluster parameters synced to DB")
    except Exception as e:
        logger.warning("Cluster sync warning: %s", e)
    finally:
        db.close()

    yield
    await progress_bridge.stop()
    logger.info("TheCee backend shutting down")


app = FastAPI(
    title="TheCee API",
    description="Pre-launch behavioral simulation platform.",
    version="1.0.0",
    # OpenAPI surface is gated by environment: in production the auto-
    # generated docs (/docs, /redoc, /openapi.json) leak the full route
    # map and request/response schemas, which helps attackers enumerate
    # endpoints and craft payloads. Disable them outside development so
    # the deployment surface matches what we intend to expose.
    docs_url="/docs" if settings.ENVIRONMENT.lower() != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT.lower() != "production" else None,
    openapi_url=(
        "/openapi.json"
        if settings.ENVIRONMENT.lower() != "production"
        else None
    ),
    lifespan=lifespan,
)

app.add_exception_handler(TheCeeError, thecee_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

app.add_middleware(TimingMiddleware)
# Audit log must wrap TimingMiddleware so the request has already been
# served (response object available) before we attempt the DB insert.
# Adding it AFTER TimingMiddleware means it runs FIRST on the request
# path and LAST on the response path — Starlette middleware order is
# last-added = outermost, so audit sees the post-Timing response and
# its timing headers.
app.add_middleware(AuditLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins(),
    allow_credentials=False,
    # The Cee API only uses GET and POST — restricting methods prevents
    # an attacker page in the allowlist from driving PUT/PATCH/DELETE
    # against the backend via preflight. ``allow_headers`` is similarly
    # locked to the small set the API actually inspects (Authorization
    # for Bearer tokens, Content-Type for JSON bodies, X-Forwarded-For
    # so the rate limiter can honour the reverse-proxy client IP,
    # Origin so the CORS handshake itself can negotiate).
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Forwarded-For", "Origin"],
    expose_headers=[
        "Content-Disposition",
        "Content-Length",
        "X-Response-Time",
        "X-Request-ID",
    ],
)

# Request correlation IDs must be the outermost application middleware so
# every downstream middleware (audit, timing) and route handler sees
# ``request.state.request_id`` before doing any work, and every response —
# including CORS preflights — carries the ``X-Request-ID`` header back to
# the caller. Added after CORS so it also wraps the CORS middleware.
app.add_middleware(RequestIdMiddleware)


@app.middleware("http")
async def set_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.ENVIRONMENT.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    # Generated-UI serve endpoints are intentionally embedded in iframes on the
    # frontend.  They control framing via Content-Security-Policy: frame-ancestors
    # set in the route handler itself, so we skip the global DENY here.
    if not request.url.path.rstrip("/").endswith("/serve"):
        response.headers["X-Frame-Options"] = "DENY"
    return response


app.include_router(api_router)


def _service_health() -> tuple[dict[str, object], int]:
    report: dict[str, object] = {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(UTC).isoformat(),
        "services": {},
    }
    status_code = 200

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        report["services"]["database"] = {"status": "healthy"}
    except Exception:
        report["services"]["database"] = {"status": "unhealthy"}
        report["status"] = "unhealthy"
        status_code = 503

    redis_client = get_redis_client()
    if redis_client is None:
        report["services"]["redis"] = {"status": "unconfigured"}
    else:
        try:
            redis_client.ping()
            report["services"]["redis"] = {"status": "healthy"}
        except Exception:
            report["services"]["redis"] = {"status": "unhealthy"}
            report["status"] = "unhealthy"
            status_code = 503

    try:
        inspector = _celery_app.control.inspect(timeout=2.0)
        active_workers = inspector.ping() or {}
        # Mirror the count into the Prometheus gauge so /metrics and /health
        # stay in agreement without a second inspector round-trip.
        metrics.set_celery_workers_online(len(active_workers))
        report["services"]["celery"] = {
            "status": "healthy" if active_workers else "degraded",
            "workers_online": len(active_workers),
        }
    except Exception:
        report["services"]["celery"] = {"status": "degraded"}

    return report, status_code


@app.get(
    "/celery/status",
    tags=["system"],
    summary="Celery worker and broker status",
    responses={200: {"description": "Broker URL and worker reachability", "content": {"application/json": {}}}},
)
async def celery_status():
    try:
        result = _celery_app.control.inspect(timeout=2.0)
        active_workers = result.active()
        return {
            "status": "configured",
            "workers_online": len(active_workers) if active_workers else 0,
        }
    except Exception:
        return {
            "status": "configured",
            "workers_online": 0,
            "note": "Worker not running or broker unreachable",
        }


@app.get(
    "/",
    tags=["system"],
    summary="API service metadata",
    responses={200: {"description": "Service name and version", "content": {"application/json": {}}}},
)
async def root():
    return {
        "status": "running",
        "product": "TheCee API",
        "version": "1.0.0",
    }


@app.get(
    "/health",
    tags=["system"],
    summary="Liveness probe",
    responses={200: {"description": "Health status", "content": {"application/json": {}}}},
)
async def health():
    payload, status_code = _service_health()
    return JSONResponse(content=payload, status_code=status_code)


# K8s-style readiness probe. Distinct from /health so a process that has
# started but hasn't finished warming up (e.g. migrations still running,
# clusters not yet synced to DB) can be removed from the load-balancer
# rotation without restarting. Returns 200 only when DB + Redis are both
# reachable; Celery is reported but does NOT gate readiness — simulations
# can run synchronously in tests / local dev, so a missing worker isn't
# sufficient reason to drop traffic.
@app.get(
    "/readyz",
    tags=["system"],
    summary="Readiness probe (DB + Redis reachable)",
    responses={
        200: {"description": "Process is ready to serve traffic", "content": {"application/json": {}}},
        503: {"description": "Process is not yet ready", "content": {"application/json": {}}},
    },
)
async def readyz() -> JSONResponse:
    checks: dict[str, dict[str, object]] = {}

    # Database — same query as /health; an exception here means the pool is
    # exhausted or the connection is broken, both reason enough to drop out
    # of rotation until it recovers.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
        db_ok = True
    except Exception as exc:
        checks["database"] = {"status": "error", "error": str(exc)[:200]}
        db_ok = False

    # Redis — unconfigured (no REDIS_URL) is treated as ready because the
    # rest of the app degrades gracefully when the cache is absent. Only
    # an actual ping failure marks us not-ready.
    redis_client = get_redis_client()
    if redis_client is None:
        checks["redis"] = {"status": "unconfigured"}
        redis_ok = True
    else:
        try:
            redis_client.ping()
            checks["redis"] = {"status": "ok"}
            redis_ok = True
        except Exception as exc:
            checks["redis"] = {"status": "error", "error": str(exc)[:200]}
            redis_ok = False

    body = {
        "ready": db_ok and redis_ok,
        "checks": checks,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    code = 200 if body["ready"] else 503
    return JSONResponse(content=body, status_code=code)


# Prometheus text format requires the exact content type below — including
# the version param — otherwise some scrapers reject the payload.
_PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@app.get(
    "/metrics",
    tags=["system"],
    summary="Prometheus metrics endpoint",
    responses={200: {"description": "Metrics in Prometheus text exposition format", "content": {"text/plain": {}}}},
)
async def prometheus_metrics() -> Response:
    # Refresh the worker gauge right before render so the snapshot reflects
    # current liveness. This is cheap (a 2s timeout ping) and gives a
    # useful "workers_online" view for the SRE dashboard.
    try:
        inspector = _celery_app.control.inspect(timeout=2.0)
        active = inspector.ping() or {}
        metrics.set_celery_workers_online(len(active))
    except Exception:
        # Don't fail the scrape just because Celery is unreachable.
        pass

    # Refresh the DB pool gauge from the SQLAlchemy engine. ``pool`` is the
    # connection pool; ``checkedout`` is the in-use count. SQLAlchemy
    # exposes this on every supported DBAPI; guard for missing attrs.
    try:
        pool = engine.pool
        checked_out = getattr(pool, "checkedout", None)
        if callable(checked_out):
            checked_out = checked_out()
        if checked_out is not None:
            metrics.set_db_pool_checked_out(int(checked_out))
    except Exception:
        pass

    body = metrics.render()
    return Response(content=body, media_type="text/plain", headers={"Content-Type": _PROM_CONTENT_TYPE})
