"""Pure live-progress delivery health digest builder.

The simulation-progress WebSocket path is the most distributed piece of
the app: Celery workers publish progress to a Redis pub/sub channel and the
API process's :class:`ProgressBridge` subscriber fans those payloads out to
connected WebSocket clients. When Redis is unconfigured, delivery falls
back to same-process-only sockets and polling remains the reliable path.

This module turns that runtime state into the ``/system/websocket-health``
digest: verdict, delivery mode, subscriber state, live listener count, the
Redis reachability probe, and any recent publish-outage age. The builder is
pure Python (no Redis, no asyncio, no I/O) so it is verifiable without
FastAPI or a live cache. Like request/query/cache health, the state is
per-process: multi-worker deployments scrape each replica individually.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.metrics import metrics

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_WATCH: str = "WATCH"
VERDICT_DEGRADED: str = "DEGRADED"
VERDICT_UNCONFIGURED: str = "UNCONFIGURED"

# Delivery modes describe the architecture actually in use, independent of
# the live reachability of Redis.
MODE_REDIS_CROSS_PROCESS: str = "REDIS_CROSS_PROCESS"
MODE_REDIS_STANDBY: str = "REDIS_CONFIGURED_STANDBY"
MODE_IN_PROCESS_FALLBACK: str = "IN_PROCESS_FALLBACK"

# Age bands for a publish-outage in this process (seconds). A recent publish
# failure means progress messages are not reaching Redis, so the subscriber
# cannot relay them. Inside the circuit-breaker window the publisher is
# still actively dropping attempts (DEGRADED); once the breaker opens and
# recovery has had a few minutes to settle, the outage is WATCH until it
# ages out entirely.
OUTAGE_DEGRADED_SECONDS: float = 15.0
OUTAGE_WATCH_SECONDS: float = 300.0

_HEALTHY_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_HEALTHY, VERDICT_UNCONFIGURED}
)


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative int, or ``default`` when unusable."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _safe_float(value: Any) -> float | None:
    """Coerce a value to a finite non-negative float, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed < 0.0 or parsed in (
        float("inf"),
        float("-inf"),
    ):
        return None
    return parsed


def _delivery_mode(*, redis_configured: bool, bridge_running: bool) -> str:
    """Describe which delivery architecture is in use."""
    if not redis_configured:
        return MODE_IN_PROCESS_FALLBACK
    if bridge_running:
        return MODE_REDIS_CROSS_PROCESS
    return MODE_REDIS_STANDBY


def _verdict(
    *,
    redis_configured: bool,
    redis_reachable: bool | None,
    bridge_running: bool,
    connection_count: int,
    last_publish_failure_age: float | None,
) -> tuple[str, list[str]]:
    """Derive the digest verdict and human reasons for it."""
    if not redis_configured:
        return VERDICT_UNCONFIGURED, [
            "Redis is not configured — progress updates reach only "
            "same-process clients; polling the progress endpoint remains "
            "the reliable fallback"
        ]

    reasons: list[str] = []
    if redis_reachable is False:
        reasons.append(
            "Redis is configured but unreachable — live cross-process "
            "delivery is down and the subscriber is retrying"
        )
        return VERDICT_DEGRADED, reasons

    if (
        last_publish_failure_age is not None
        and last_publish_failure_age <= OUTAGE_DEGRADED_SECONDS
    ):
        reasons.append(
            f"Last progress publish failed {last_publish_failure_age:.0f}s "
            "ago — payloads are not reaching the Redis channel"
        )
        return VERDICT_DEGRADED, reasons

    if (
        last_publish_failure_age is not None
        and last_publish_failure_age <= OUTAGE_WATCH_SECONDS
    ):
        reasons.append(
            f"Last progress publish failed {last_publish_failure_age:.0f}s "
            "ago — recovery is in progress"
        )
        return VERDICT_WATCH, reasons

    if not bridge_running:
        if connection_count > 0:
            reasons.append(
                "Subscriber is not running while clients are connected — "
                "connected sockets cannot receive cross-process updates"
            )
            return VERDICT_DEGRADED, reasons
        # Standby with no listeners is healthy by design: the subscriber
        # starts lazily on the first WebSocket connection.
        reasons.append(
            "Subscriber is not running yet — it starts lazily on the "
            "first WebSocket connection"
        )
        return VERDICT_HEALTHY, reasons

    return VERDICT_HEALTHY, []


def _narrative(
    *,
    verdict: str,
    delivery_mode: str,
    bridge_running: bool,
    connection_count: int,
    redis_reachable: bool | None,
    last_publish_failure_age: float | None,
) -> str:
    """One-paragraph plain-text summary for dashboards."""
    listeners = (
        f"{connection_count} live listener(s)"
        if connection_count > 0
        else "no live listeners"
    )
    if verdict == VERDICT_UNCONFIGURED:
        return (
            "Redis is not configured, so live progress is delivered only "
            f"within the API process ({listeners}); polling "
            "/simulations/{id}/progress remains the reliable path."
        )
    if verdict == VERDICT_DEGRADED:
        return (
            "Live progress delivery is degraded: "
            f"{delivery_mode} mode, subscriber "
            f"{'running' if bridge_running else 'not running'}, "
            f"{listeners}, Redis "
            f"{'reachable' if redis_reachable else 'unreachable'}"
            + (
                f", last publish failure {last_publish_failure_age:.0f}s ago"
                if last_publish_failure_age is not None
                else ""
            )
            + "."
        )
    if verdict == VERDICT_WATCH:
        return (
            "Live progress delivery recovered from a recent publish "
            f"failure ({delivery_mode} mode, {listeners}); "
            "monitor the next progress tick to confirm steady state."
        )
    if not bridge_running:
        return (
            "Live progress delivery is healthy (standby): Redis is "
            "configured but the subscriber has not started yet — it "
            f"starts lazily on the first WebSocket connection ({listeners})."
        )
    return (
        "Live progress delivery is healthy: Redis pub/sub subscriber is "
        f"running with {listeners} on the progress channel."
    )


def build_websocket_health(
    *,
    redis_configured: bool,
    redis_reachable: bool | None = None,
    bridge_running: bool = False,
    connection_count: int = 0,
    connected_simulation_ids: list[int] | None = None,
    last_publish_failure_age_seconds: float | None = None,
    channel: str = "",
    reconnect_delay_seconds: float = 5.0,
    circuit_breaker_seconds: float = 15.0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the websocket/progress-bridge health digest.

    Args:
        redis_configured: whether a Redis client is configured.
        redis_reachable: live PING result (``None`` when unconfigured).
        bridge_running: whether the API process's subscriber loop is alive.
        connection_count: live WebSocket connections in this process.
        connected_simulation_ids: simulation ids with a live socket
            (capped by the caller).
        last_publish_failure_age_seconds: age of the last publish failure
            in this process, or ``None`` when none occurred.
        channel: the Redis pub/sub channel name.
        reconnect_delay_seconds: subscriber reconnect backoff.
        circuit_breaker_seconds: publisher circuit-breaker window.
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        A dict matching :class:`WebsocketHealthOut` with verdict, healthy
        flag, delivery mode, subscriber/listener state, reasons and a
        plain-text narrative.
    """
    connection_count = _safe_int(connection_count)
    ids = [
        _safe_int(simulation_id)
        for simulation_id in (connected_simulation_ids or [])
        if _safe_int(simulation_id) > 0
    ]
    outage_age = _safe_float(last_publish_failure_age_seconds)

    verdict, reasons = _verdict(
        redis_configured=bool(redis_configured),
        redis_reachable=redis_reachable,
        bridge_running=bool(bridge_running),
        connection_count=connection_count,
        last_publish_failure_age=outage_age,
    )
    mode = _delivery_mode(
        redis_configured=bool(redis_configured),
        bridge_running=bool(bridge_running),
    )

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "healthy": verdict in _HEALTHY_VERDICTS,
        "delivery_mode": mode,
        "bridge_running": bool(bridge_running),
        "redis_configured": bool(redis_configured),
        "redis_reachable": redis_reachable,
        "connection_count": connection_count,
        "connected_simulation_ids": ids,
        "last_publish_failure_age_seconds": outage_age,
        "channel": str(channel or ""),
        "reconnect_delay_seconds": _safe_float(reconnect_delay_seconds)
        or 0.0,
        "circuit_breaker_seconds": _safe_float(circuit_breaker_seconds)
        or 0.0,
        "reasons": reasons,
        "narrative": _narrative(
            verdict=verdict,
            delivery_mode=mode,
            bridge_running=bool(bridge_running),
            connection_count=connection_count,
            redis_reachable=redis_reachable,
            last_publish_failure_age=outage_age,
        ),
    }


def record_websocket_gauges(payload: dict[str, Any]) -> None:
    """Mirror the digest's live numbers into Prometheus gauges.

    Keeps ``/metrics`` fresh even when only the standalone endpoint is
    polled, matching how worker-health and database-pool-health mirror
    their snapshots. Fields that were not measured stay unset so an absent
    probe never masquerades as a zero value: ``redis_reachable`` remains
    unset while Redis is unconfigured, and the publish-failure-age gauge
    is only written once a failure has actually been observed.
    """
    metrics.set_websocket_connections(
        _safe_int(payload.get("connection_count"))
    )
    metrics.set_websocket_bridge_running(bool(payload.get("bridge_running")))
    metrics.set_websocket_redis_configured(
        bool(payload.get("redis_configured"))
    )
    reachable = payload.get("redis_reachable")
    if reachable is not None:
        metrics.set_websocket_redis_reachable(bool(reachable))
    outage_age = _safe_float(payload.get("last_publish_failure_age_seconds"))
    if outage_age is not None:
        metrics.set_websocket_last_publish_failure_age(outage_age)
    verdict = str(payload.get("verdict") or VERDICT_UNCONFIGURED)
    metrics.set_websocket_unhealthy(verdict not in _HEALTHY_VERDICTS)


__all__ = [
    "MODE_IN_PROCESS_FALLBACK",
    "MODE_REDIS_CROSS_PROCESS",
    "MODE_REDIS_STANDBY",
    "OUTAGE_DEGRADED_SECONDS",
    "OUTAGE_WATCH_SECONDS",
    "VERDICT_DEGRADED",
    "VERDICT_HEALTHY",
    "VERDICT_UNCONFIGURED",
    "VERDICT_WATCH",
    "build_websocket_health",
    "record_websocket_gauges",
]
