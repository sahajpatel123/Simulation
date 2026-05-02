from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections keyed by simulation_id.
    """

    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}

    async def connect(
        self, websocket: WebSocket, simulation_id: int, *, skip_accept: bool = False
    ) -> None:
        if not skip_accept:
            await websocket.accept()
        # Evict stale connection if present.
        if simulation_id in self._connections:
            try:
                await self._connections[simulation_id].close(code=1001)
            except Exception as _exc:
                logger.debug(
                    "%s suppressed: %s",
                    __name__,
                    _exc,
                )
        self._connections[simulation_id] = websocket
        logger.info(f"[WS] Client connected - simulation_id={simulation_id}")

    def disconnect(self, simulation_id: int) -> None:
        self._connections.pop(simulation_id, None)
        logger.info(f"[WS] Client disconnected - simulation_id={simulation_id}")

    async def send_update(self, simulation_id: int, payload: dict[str, Any]) -> bool:
        ws = self._connections.get(simulation_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(payload, default=str))
            return True
        except Exception as exc:
            logger.warning(f"[WS] Send failed simulation_id={simulation_id}: {exc}")
            self.disconnect(simulation_id)
            return False

    async def broadcast_progress(
        self,
        simulation_id: int,
        status: str,
        stage: str,
        pct: int,
        agents_processed: int = 0,
        agents_total: int = 0,
        extra: dict | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": "progress",
            "simulation_id": simulation_id,
            "status": status,
            "stage": stage,
            "pct": pct,
            "agents_processed": agents_processed,
            "agents_total": agents_total,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            payload.update(extra)
        await self.send_update(simulation_id, payload)

    def is_connected(self, simulation_id: int) -> bool:
        return simulation_id in self._connections

    @property
    def connection_count(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()


def sync_broadcast(
    simulation_id: int,
    status: str,
    stage: str,
    pct: int,
    agents_processed: int = 0,
    agents_total: int = 0,
    extra: dict | None = None,
) -> None:
    """
    Synchronous bridge for Celery tasks.
    """
    if not ws_manager.is_connected(simulation_id):
        return
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            ws_manager.broadcast_progress(
                simulation_id=simulation_id,
                status=status,
                stage=stage,
                pct=pct,
                agents_processed=agents_processed,
                agents_total=agents_total,
                extra=extra,
            )
        )
    except Exception as exc:
        logger.warning(f"[WS] sync_broadcast failed simulation_id={simulation_id}: {exc}")
    finally:
        try:
            asyncio.set_event_loop(None)
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )
        if loop is not None:
            loop.close()

