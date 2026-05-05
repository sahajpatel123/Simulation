from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import engine, init_extensions
from app.core.errors import TheCeeError, generic_error_handler, thecee_error_handler
from app.core.logging_config import configure_logging
from app.core.redis_client import get_redis_client
from app.core.timing_middleware import TimingMiddleware
from app.worker import celery_app as _celery_app

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
    print("✅ TheCee backend running — pgvector enabled")

    from app.simulation.clusters.registry import ClusterRegistry
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        ClusterRegistry().sync_to_db(db)
        print("✅ Cluster parameters synced to DB")
    except Exception as e:
        print(f"⚠️ Cluster sync warning: {e}")
    finally:
        db.close()

    yield
    print("TheCee backend shutting down")


app = FastAPI(
    title="TheCee API",
    description="Pre-launch behavioral simulation platform.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_exception_handler(TheCeeError, thecee_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

app.add_middleware(TimingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "X-Response-Time"],
)


@app.middleware("http")
async def set_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.ENVIRONMENT.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return response


app.include_router(api_router)


def _service_health() -> tuple[dict[str, object], int]:
    report: dict[str, object] = {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {},
    }
    status_code = 200

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        report["services"]["database"] = {"status": "healthy"}
    except Exception as exc:
        report["services"]["database"] = {"status": "unhealthy", "detail": str(exc)}
        report["status"] = "unhealthy"
        status_code = 503

    redis_client = get_redis_client()
    if redis_client is None:
        report["services"]["redis"] = {"status": "unconfigured"}
    else:
        try:
            redis_client.ping()
            report["services"]["redis"] = {"status": "healthy"}
        except Exception as exc:
            report["services"]["redis"] = {"status": "unhealthy", "detail": str(exc)}
            report["status"] = "unhealthy"
            status_code = 503

    try:
        inspector = _celery_app.control.inspect(timeout=2.0)
        active_workers = inspector.ping() or {}
        report["services"]["celery"] = {
            "status": "healthy" if active_workers else "degraded",
            "workers_online": len(active_workers),
        }
    except Exception as exc:
        report["services"]["celery"] = {"status": "degraded", "detail": str(exc)}

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
            "broker": settings.CELERY_BROKER_URL,
            "workers_online": len(active_workers) if active_workers else 0,
        }
    except Exception:
        return {
            "status": "configured",
            "broker": settings.CELERY_BROKER_URL,
            "workers_online": 0,
            "note": "Worker not running or Redis unreachable",
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
