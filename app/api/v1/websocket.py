from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
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
    email = decode_token(token, token_type="access")
    if not email:
        return None
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first()
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


@router.websocket("/ws/simulation/{simulation_id}")
async def websocket_simulation_progress(
    websocket: WebSocket,
    simulation_id: int,
    token: str = Query(..., description="JWT access token"),
):
    user = await _get_user_from_token(token)
    if user is None:
        await websocket.close(code=4001)
        return

    owns = await _verify_ownership(simulation_id, user.id)
    if not owns:
        await websocket.close(code=4003)
        return

    await ws_manager.connect(websocket, simulation_id)

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

