from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.deps import user_from_access_sub
from app.core.security import decode_token
from app.core.websocket import ws_manager
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


def _origin_allowed(origin: str | None) -> bool:
    """Return True iff the WebSocket Origin is in the CORS allowlist.

    Browsers send ``Origin`` on the WebSocket handshake; we use the same
    allowlist the HTTP CORS middleware uses (``settings.cors_allowed_origins``)
    so a frontend at ``FRONTEND_URL`` (or ``localhost`` in dev) is the only
    place that can open a socket. Non-browser clients (curl, server-to-server)
    may not send Origin — we treat absence as "allowed" only in non-production
    so internal tooling keeps working. In production, missing Origin is
    rejected as a defence against headless attackers.
    """
    allowed = settings.cors_allowed_origins()
    if not origin:
        # In production, missing Origin on a WebSocket handshake is treated
        # as a hostile client — browsers always send it.
        return settings.ENVIRONMENT.lower() != "production"
    return origin in allowed


async def _get_user_from_token(token: str) -> User | None:
    if not token:
        return None
    sub = decode_token(token, token_type="access")
    if not sub:
        return None
    db = SessionLocal()
    try:
        return user_from_access_sub(db, sub)
    finally:
        db.close()


async def _verify_ownership(simulation_id: int, user_id: int) -> bool:
    db = SessionLocal()
    try:
        sim = (
            db.query(Simulation)
            .join(Project, Simulation.project_id == Project.id)
            .filter(Simulation.id == simulation_id, Project.user_id == user_id)
            .first()
        )
        return sim is not None
    finally:
        db.close()


@router.websocket(
    "/ws/simulation/{simulation_id}",
    name="Stream simulation progress (WebSocket)",
)
async def websocket_simulation_progress(
    websocket: WebSocket,
    simulation_id: int,
):
    """Auth: first frame must be JSON `{"type":"auth","access_token":"<jwt>"}` (not in URL)."""
    # Reject cross-origin WebSocket handshakes (CSWSH). The browser sends
    # ``Origin`` on the upgrade request; we validate against the same
    # allowlist used for HTTP CORS. Validation runs BEFORE
    # ``websocket.accept()`` so a hostile origin never establishes a
    # connection — we close before the protocol upgrade completes.
    origin = websocket.headers.get("origin") or websocket.headers.get("Origin")
    if not _origin_allowed(origin):
        logger.warning(
            "[WS] Rejected handshake: origin=%r not in allowlist",
            origin,
        )
        await websocket.close(code=4003)
        return
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
    except asyncio.TimeoutError:
        await websocket.close(code=4001)
        return
    except Exception:
        await websocket.close(code=4001)
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.close(code=4001)
        return
    if payload.get("type") != "auth":
        await websocket.close(code=4001)
        return
    token = payload.get("access_token") or payload.get("token")
    if not token or not isinstance(token, str):
        await websocket.close(code=4001)
        return

    user = await _get_user_from_token(token)
    if user is None:
        await websocket.close(code=4001)
        return

    owns = await _verify_ownership(simulation_id, user.id)
    if not owns:
        await websocket.close(code=4003)
        return

    await ws_manager.connect(websocket, simulation_id, skip_accept=True)

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if len(data) > 65536:
                    logger.warning(
                        "[WS] Oversized frame rejected simulation_id=%s len=%s",
                        simulation_id,
                        len(data),
                    )
                    await websocket.send_text(
                        '{"type":"error","message":"Frame too large (max 64KB)"}'
                    )
                    continue
                if data.strip() == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.warning(f"[WS] Receive error simulation_id={simulation_id}: {exc}")
                break
    finally:
        ws_manager.disconnect(simulation_id)
