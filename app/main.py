from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import init_extensions
from app.core.logging_config import configure_logging
from app.core.timing_middleware import TimingMiddleware
from app.worker import celery_app as _celery_app


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
    title="TheCee Simulation Engine",
    description="Agent-based startup simulation platform",
    version="0.1.0",
    lifespan=lifespan,
)

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


@app.get("/celery/status")
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


@app.get("/")
async def root():
    return {
        "status": "running",
        "product": "TheCee Simulation Engine",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
