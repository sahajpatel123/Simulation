from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.deps import user_from_access_sub
from app.core.progress_bridge import progress_bridge
from app.core.security import decode_token, log_safe
from app.core.websocket import ws_manager
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

# How long an accepted-but-unauthenticated socket may sit waiting for its
# auth frame. A real frontend sends it immediately; every extra second is
# a free slot for anonymous socket-holding (each idle connection pins a
# TCP socket plus an asyncio task).
PRE_AUTH_TIMEOUT_SECONDS = 5

# App-level frame cap, enforced BEFORE the payload reaches handlers. The
# ASGI server also caps frames (uvicorn ws_max_size, default 16MB), but
# that is far above anything this protocol needs and would still allow a
# 16MB allocation per frame per socket; enforcing here makes the real
# limit explicit and survivable.
MAX_FRAME_CHARS = 65536


async def _receive_limited(
    websocket: WebSocket,
    timeout: float | None,
) -> tuple[str | None, bool]:
    """Receive one text frame bounded by ``timeout`` and MAX_FRAME_CHARS.

    Returns ``(text, False)`` on success, ``(None, True)`` when a text
    frame arrived but exceeded the cap (its contents are never handed to
    handlers), and ``(None, False)`` on disconnect / non-message events /
    binary frames (the protocol is text-only). Propagates transport
    errors to the caller's existing handling.
    """
    message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
    if message.get("type") != "websocket.receive":
        return None, False
    text = message.get("text")
    if text is None:
        return None, False
    if len(text) > MAX_FRAME_CHARS:
        logger.warning(
            "[WS] Oversized frame rejected len=%d cap=%d",
            len(text),
            MAX_FRAME_CHARS,
        )
        return None, True
    return text, False


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
            log_safe(origin).replace("\n", " "),
        )
        await websocket.close(code=4003)
        return
    await websocket.accept()
    try:
        raw, oversize = await _receive_limited(websocket, PRE_AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await websocket.close(code=4001)
        return
    except Exception:
        await websocket.close(code=4001)
        return
    if oversize or raw is None:
        # Oversized, binary, or non-message first frame — never even parse it.
        await websocket.close(code=4001)
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.close(code=4001)
        return
    # A syntactically valid but non-object frame ("[]" / "5" / '"x"') has
    # no .get() — reject it here rather than crashing the handler with an
    # unhandled AttributeError.
    if not isinstance(payload, dict):
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
    # Ensure this process can receive progress published by Celery workers
    # (restarts the subscriber after a Redis outage without a full app
    # restart). Safe to call repeatedly.
    await progress_bridge.ensure_running()

    try:
        while True:
            try:
                data, oversize = await _receive_limited(websocket, None)
                if oversize:
                    await websocket.send_text(
                        '{"type":"error","message":"Frame too large (max 64KB)"}'
                    )
                    continue
                if data is None:
                    # Binary or non-message event — not part of this protocol.
                    break
                if data.strip() == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.warning(
                    "[WS] Receive error simulation_id=%s: %s",
                    log_safe(simulation_id).replace("\n", " "),
                    log_safe(exc).replace("\n", " "),
                )
                break
    finally:
        ws_manager.disconnect(simulation_id)
