"""Pydantic schemas for the combined system health summary."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SystemHealthCheck(BaseModel):
    """One service's health probe result."""

    status: str = ""
    latency_ms: float | None = None
    error: str | None = None
    worker_reachable: bool | None = None
    workers_online: int | None = None


class SystemHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/health``."""

    status: str = "degraded"
    healthy: bool = False
    checked_at: str = ""
    checks: dict[str, SystemHealthCheck] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class RequestHealthRoute(BaseModel):
    """Per-route request-health row from ``GET /api/v1/system/request-health``."""

    method: str = ""
    path: str = ""
    request_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p50_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)
    p99_latency_ms: float | None = Field(default=None, ge=0.0)
    max_bucket_ms: float | None = Field(default=None, ge=0.0)


class RequestHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/request-health``."""

    generated_at: str = ""
    total_requests: int = Field(default=0, ge=0)
    total_errors: int = Field(default=0, ge=0)
    overall_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    route_count: int = Field(default=0, ge=0)
    routes: list[RequestHealthRoute] = Field(default_factory=list)


__all__ = [
    "RequestHealthOut",
    "RequestHealthRoute",
    "SystemHealthCheck",
    "SystemHealthOut",
]
