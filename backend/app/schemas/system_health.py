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


__all__ = ["SystemHealthCheck", "SystemHealthOut"]
