from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.database import init_extensions
from app.worker import celery_app as _celery_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_extensions()
    print("✅ TheCee backend running — pgvector enabled")
    yield
    print("TheCee backend shutting down")


app = FastAPI(
    title="TheCee Simulation Engine",
    description="Agent-based startup simulation platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length"],
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
