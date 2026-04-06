from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import init_extensions


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
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


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
