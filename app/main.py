from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import init_extensions
from app.core.errors import TheCeeError, generic_error_handler, thecee_error_handler
from app.core.logging_config import configure_logging
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

# CORS: in production, only the configured FRONTEND_URL. Bearer tokens (not cookies).
_default_origins = ["http://localhost:3000", "http://localhost:3001"]
if settings.ENVIRONMENT.lower() == "production":
    _allowed_origins: list[str] = [settings.FRONTEND_URL] if settings.FRONTEND_URL else []
else:
    _allowed_origins = (
        [settings.FRONTEND_URL, *_default_origins]
        if settings.FRONTEND_URL not in _default_origins
        else _default_origins
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "X-Response-Time"],
)

app.include_router(api_router)


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
    return {"status": "healthy"}
