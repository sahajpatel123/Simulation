"""Redis pub/sub bridge for live simulation-progress WebSocket delivery.

The Celery worker and the FastAPI process run in separate processes in
production. ``sync_broadcast()`` (called from Celery tasks) therefore cannot
reach WebSocket clients connected to the API process directly. This module
closes that gap:

* ``publish_sync()`` — synchronous publisher used by Celery tasks. Publishes
  the progress payload to a Redis channel when Redis is available and fails
  fast (with a short circuit-breaker window) when it is not.
* The subscriber loop (``_run``) — an asyncio task owned by the API process
  (started from the app lifespan and lazily from the WebSocket route). It
  listens on the same channel and fans each payload out to the in-process
  ``ConnectionManager``.

When Redis is unavailable, ``sync_broadcast`` keeps the legacy behaviour of
delivering only to clients connected in the same process (local dev), so
existing polling-based fallbacks remain the reliable path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from redis import Redis

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Single channel for all simulation progress events. Kept here (not in
# settings) because worker and API processes must agree on the channel name
# and it is not environment-specific.
PROGRESS_CHANNEL = "thecee:simulation-progress"

# After a publish failure (e.g. Redis down), skip further publish attempts for
# this many seconds. Redis client connect timeouts are ~2s each; without the
# breaker every progress tick would stall the Celery task for the full
# timeout while Redis is down.
_CIRCUIT_BREAKER_SECONDS = 15.0


class ProgressBridge:
    """Cross-process progress relay: publish (sync) + subscribe (async)."""

    def __init__(
        self,
        client: Redis | None = None,
        channel: str = PROGRESS_CHANNEL,
    ) -> None:
        self._client = client
        self._channel = channel
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._running = False
        self._last_publish_failure: float = 0.0

    def is_running(self) -> bool:
        """True when this process has a live subscriber on the channel."""
        return self._running

    async def ensure_running(self) -> bool:
        """Start the subscriber loop once; safe to call repeatedly."""
        async with self._lock:
            if self._running:
                return True
            if self._task is not None and not self._task.done():
                return True
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())
            return True

    async def stop(self) -> None:
        """Stop the subscriber loop and release the Redis subscription."""
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                # Cancellation is the expected exit path for stop().
                pass
        self._running = False

    def publish_sync(self, payload: dict[str, Any]) -> bool:
        """Publish a progress payload to Redis (best effort).

        Returns True when the publish call succeeded (even with zero
        subscribers — the API process may hold the subscribers), False when
        Redis is unavailable or the call failed.
        """
        now = time.monotonic()
        breaker_active = (
            self._last_publish_failure
            and now - self._last_publish_failure < _CIRCUIT_BREAKER_SECONDS
        )
        if breaker_active:
            return False

        client = self._client
        if client is None:
            client = get_redis_client()
            self._client = client
        if client is None:
            return False
        try:
            client.publish(self._channel, json.dumps(payload, default=str))
            return True
        except Exception as exc:
            logger.warning("Redis progress publish failed: %s", exc)
            self._last_publish_failure = now
            return False

    async def _run(self) -> None:
        """Subscribe to the channel and relay messages to local sockets."""
        client = self._client
        if client is None:
            try:
                client = get_redis_client()
                self._client = client
            except Exception as exc:
                logger.warning("Progress bridge init failed: %s", exc)
                client = None
        if client is None:
            logger.info("Progress bridge disabled — Redis unavailable")
            self._running = False
            return

        pubsub = client.pubsub()
        try:
            await asyncio.to_thread(pubsub.subscribe, self._channel)
            self._running = True
            logger.info("Progress bridge subscribed to %s", self._channel)
            while not self._stop.is_set():
                message = await asyncio.to_thread(
                    pubsub.get_message,
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue
                data = message.get("data")
                if not isinstance(data, str):
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Progress bridge dropped malformed message")
                    continue
                try:
                    await self._handle_message(payload)
                except Exception as exc:
                    logger.warning("Progress bridge dispatch failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Progress bridge subscriber error: %s", exc)
        finally:
            self._running = False
            try:
                await asyncio.to_thread(pubsub.close)
            except Exception as _exc:
                logger.debug("Progress bridge pubsub close suppressed: %s", _exc)

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        """Deliver a relayed payload to the local ConnectionManager.

        ``ws_manager`` is imported lazily to keep the import graph acyclic:
        ``app.core.websocket`` imports this module at the top.
        """
        simulation_id = payload.get("simulation_id")
        if simulation_id is None:
            return
        from app.core.websocket import ws_manager

        await ws_manager.send_update(int(simulation_id), payload)


progress_bridge = ProgressBridge()
