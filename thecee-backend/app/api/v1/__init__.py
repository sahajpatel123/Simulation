from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.decisions import router as decisions_router
from app.api.v1.projects import router as projects_router
from app.api.v1.simulations import router as simulations_router
from app.api.v1.websocket import router as ws_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(decisions_router)
api_router.include_router(simulations_router)
api_router.include_router(ws_router)
