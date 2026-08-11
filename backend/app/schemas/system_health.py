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


class WorkerHealthBroker(BaseModel):
    """Broker probe section from ``/system/worker-health``."""

    status: str = "unconfigured"
    scheme: str = ""
    database: int | None = Field(default=None, ge=0)
    error: str | None = None


class WorkerHealthWorker(BaseModel):
    """Per-worker row from ``/system/worker-health``."""

    hostname: str = ""
    concurrency: int | None = Field(default=None, ge=1)
    pid: int | None = Field(default=None, ge=0)
    prefetch_count: int | None = Field(default=None, ge=0)
    uptime_seconds: int | None = Field(default=None, ge=0)
    active_tasks: int = Field(default=0, ge=0)
    reserved_tasks: int = Field(default=0, ge=0)
    scheduled_tasks: int = Field(default=0, ge=0)


class WorkerQueueHealth(BaseModel):
    """Per-queue row from ``/system/worker-health``."""

    name: str = ""
    depth: int | None = Field(default=None, ge=0)
    active_tasks: int = Field(default=0, ge=0)
    reserved_tasks: int = Field(default=0, ge=0)
    scheduled_tasks: int = Field(default=0, ge=0)


class WorkerTotalsOut(BaseModel):
    """Aggregate in-flight and backlog counters from ``/system/worker-health``."""

    workers_online: int = Field(default=0, ge=0)
    active_tasks: int = Field(default=0, ge=0)
    reserved_tasks: int = Field(default=0, ge=0)
    scheduled_tasks: int = Field(default=0, ge=0)
    queue_depth: int = Field(default=0, ge=0)


class WorkerHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/worker-health``."""

    generated_at: str = ""
    verdict: str = "NO_DATA"
    reasons: list[str] = Field(default_factory=list)
    broker: WorkerHealthBroker = Field(default_factory=WorkerHealthBroker)
    totals: WorkerTotalsOut = Field(default_factory=WorkerTotalsOut)
    workers: list[WorkerHealthWorker] = Field(default_factory=list)
    queues: list[WorkerQueueHealth] = Field(default_factory=list)


class SimulationLatencyStats(BaseModel):
    """Completion-latency stats from ``/system/simulation-health``."""

    count: int = Field(default=0, ge=0)
    mean_ms: float | None = Field(default=None, ge=0.0)
    p50_ms: float | None = Field(default=None, ge=0.0)
    p95_ms: float | None = Field(default=None, ge=0.0)
    p99_ms: float | None = Field(default=None, ge=0.0)
    min_ms: float | None = Field(default=None, ge=0.0)
    max_ms: float | None = Field(default=None, ge=0.0)


class SimulationFailureBucket(BaseModel):
    """One coarse failure bucket from ``/system/simulation-health``."""

    bucket: str = ""
    count: int = Field(default=0, ge=0)
    latest_at: str | None = None
    sample_error: str = ""


class SimulationFailureOut(BaseModel):
    """One recent failed simulation from ``/system/simulation-health``."""

    simulation_id: int = Field(default=0, ge=0)
    project_id: int = Field(default=0, ge=0)
    created_at: str | None = None
    error_message: str = ""


class SimulationDailyTrendRow(BaseModel):
    """One day's simulation activity from ``/system/simulation-health``."""

    date: str = ""
    created: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class SimulationHealthOut(BaseModel):
    """Response from ``GET /api/v1/system/simulation-health``.

    A database-backed digest of the simulation pipeline: status counts,
    completion/failure rates, completion-latency percentiles, coarse
    failure buckets, recent failures, a zero-filled daily trend and a
    HEALTHY / WATCH / DEGRADED / NO_DATA verdict.
    """

    generated_at: str = ""
    window_days: int = Field(default=7, ge=1)
    total_simulations: int = Field(default=0, ge=0)
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    terminal_count: int = Field(default=0, ge=0)
    completion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    latency: SimulationLatencyStats = Field(default_factory=SimulationLatencyStats)
    failure_buckets: list[SimulationFailureBucket] = Field(default_factory=list)
    recent_failures: list[SimulationFailureOut] = Field(default_factory=list)
    daily_trend: list[SimulationDailyTrendRow] = Field(default_factory=list)
    oldest_running_at: str | None = None
    verdict: str = "NO_DATA"
    reasons: list[str] = Field(default_factory=list)


class SystemOverviewSubsystem(BaseModel):
    """One subsystem row from ``GET /system/overview``."""

    key: str = ""
    label: str = ""
    verdict: str = "NO_DATA"
    healthy: bool = True
    summary: str = ""
    headline: dict[str, Any] = Field(default_factory=dict)


class SystemOverviewService(BaseModel):
    """One service probe row from ``GET /system/overview``."""

    name: str = ""
    status: str = "unknown"
    latency_ms: float | None = Field(default=None, ge=0.0)
    detail: str = ""


class SystemOverviewOut(BaseModel):
    """Response from ``GET /api/v1/system/overview``."""

    generated_at: str = ""
    status: str = "degraded"
    healthy: bool = False
    unhealthy_components: list[str] = Field(default_factory=list)
    services: list[SystemOverviewService] = Field(default_factory=list)
    subsystems: list[SystemOverviewSubsystem] = Field(default_factory=list)


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
    "SimulationDailyTrendRow",
    "SimulationFailureBucket",
    "SimulationFailureOut",
    "SimulationHealthOut",
    "SimulationLatencyStats",
    "SlowQueryOut",
    "SystemHealthCheck",
    "SystemHealthOut",
    "SystemOverviewOut",
    "SystemOverviewService",
    "SystemOverviewSubsystem",
    "WorkerHealthBroker",
    "WorkerHealthOut",
    "WorkerHealthWorker",
    "WorkerQueueHealth",
    "WorkerTotalsOut",
]
