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


class QueryKindStats(BaseModel):
    """Per-statement-kind DB query stats from ``/system/query-health``."""

    kind: str = ""
    query_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)


class SlowQueryOut(BaseModel):
    """One captured slow statement from the bounded query-health ring."""

    kind: str = ""
    statement: str = ""
    duration_ms: float = Field(default=0.0, ge=0.0)
    at: str = ""


class QueryHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/query-health``."""

    generated_at: str = ""
    total_queries: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    slow_query_count: int = Field(default=0, ge=0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p50_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)
    p99_latency_ms: float | None = Field(default=None, ge=0.0)
    verdict: str = "NO_DATA"
    kinds: list[QueryKindStats] = Field(default_factory=list)
    recent_slow_queries: list[SlowQueryOut] = Field(default_factory=list)


class LLMModelStats(BaseModel):
    """Per-model LLM call stats from ``/system/llm-health``."""

    model: str = ""
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p50_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)
    p99_latency_ms: float | None = Field(default=None, ge=0.0)


class LLMTaskStats(BaseModel):
    """Per-task LLM call stats from ``/system/llm-health``."""

    task: str = ""
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p50_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)
    p99_latency_ms: float | None = Field(default=None, ge=0.0)


class LLMFailureReason(BaseModel):
    """One failure-reason bucket from ``/system/llm-health``."""

    reason: str = ""
    failure_count: int = Field(default=0, ge=0)


class LLMHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/llm-health``."""

    generated_at: str = ""
    total_attempts: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_latency_ms: float | None = Field(default=None, ge=0.0)
    p50_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_latency_ms: float | None = Field(default=None, ge=0.0)
    p99_latency_ms: float | None = Field(default=None, ge=0.0)
    verdict: str = "NO_DATA"
    models: list[LLMModelStats] = Field(default_factory=list)
    tasks: list[LLMTaskStats] = Field(default_factory=list)
    failure_reasons: list[LLMFailureReason] = Field(default_factory=list)


class CacheNamespaceStats(BaseModel):
    """Per-namespace response-cache stats from ``/system/cache-health``."""

    namespace: str = ""
    reads: int = Field(default=0, ge=0)
    hits: int = Field(default=0, ge=0)
    misses: int = Field(default=0, ge=0)
    read_error_count: int = Field(default=0, ge=0)
    unconfigured_read_count: int = Field(default=0, ge=0)
    hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    read_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    writes: int = Field(default=0, ge=0)
    write_error_count: int = Field(default=0, ge=0)
    unconfigured_write_count: int = Field(default=0, ge=0)
    write_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    invalidations: int = Field(default=0, ge=0)
    invalidation_error_count: int = Field(default=0, ge=0)
    unconfigured_invalidation_count: int = Field(default=0, ge=0)
    invalidation_error_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    current_keys: int | None = Field(default=None, ge=0)


class CacheHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/cache-health``."""

    generated_at: str = ""
    redis_configured: bool = False
    verdict: str = "NO_DATA"
    total_reads: int = Field(default=0, ge=0)
    total_hits: int = Field(default=0, ge=0)
    total_misses: int = Field(default=0, ge=0)
    read_error_count: int = Field(default=0, ge=0)
    unconfigured_read_count: int = Field(default=0, ge=0)
    hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    read_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    total_writes: int = Field(default=0, ge=0)
    write_error_count: int = Field(default=0, ge=0)
    unconfigured_write_count: int = Field(default=0, ge=0)
    write_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    total_invalidations: int = Field(default=0, ge=0)
    invalidation_error_count: int = Field(default=0, ge=0)
    unconfigured_invalidation_count: int = Field(default=0, ge=0)
    invalidation_error_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    current_keys: int | None = Field(default=None, ge=0)
    namespaces: list[CacheNamespaceStats] = Field(default_factory=list)


__all__ = [
    "CacheHealthOut",
    "CacheNamespaceStats",
    "LLMFailureReason",
    "LLMHealthOut",
    "LLMModelStats",
    "LLMTaskStats",
    "QueryHealthOut",
    "QueryKindStats",
    "RequestHealthOut",
    "RequestHealthRoute",
    "SlowQueryOut",
    "SystemHealthCheck",
    "SystemHealthOut",
]
