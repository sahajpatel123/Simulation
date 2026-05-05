from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.deps import user_from_access_sub
from app.core.security import decode_token
from app.core.websocket import ws_manager
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


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
                if data.strip() == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.warning(f"[WS] Receive error simulation_id={simulation_id}: {exc}")
                break
    finally:
        ws_manager.disconnect(simulation_id)
