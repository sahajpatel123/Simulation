from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.calibration import router as calibration_router
from app.api.v1.decisions import router as decisions_router
from app.api.v1.outcomes import router as outcomes_router
from app.api.v1.projects import router as projects_router
from app.api.v1.reports import router as reports_router
from app.api.v1.simulations import router as simulations_router
from app.api.v1.users import router as users_router
from app.api.v1.websocket import router as ws_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(calibration_router)
api_router.include_router(projects_router)
api_router.include_router(decisions_router)
api_router.include_router(outcomes_router)
api_router.include_router(reports_router)
api_router.include_router(simulations_router)
api_router.include_router(users_router)
api_router.include_router(ws_router)
