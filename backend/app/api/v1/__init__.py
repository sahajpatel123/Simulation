from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.assumption_evidence import router as assumption_evidence_router
from app.api.v1.auth import router as auth_router
from app.api.v1.billing import router as billing_router
from app.api.v1.calibration import router as calibration_router
from app.api.v1.decisions import router as decisions_router
from app.api.v1.experiments import router as experiments_router
from app.api.v1.hardware import router as hardware_router
from app.api.v1.outcomes import router as outcomes_router
from app.api.v1.project_overview import router as project_overview_router
from app.api.v1.projects import router as projects_router
from app.api.v1.reports import router as reports_router
from app.api.v1.share import router as share_router
from app.api.v1.simulation_webhooks import router as simulation_webhooks_router
from app.api.v1.simulations import router as simulations_router
from app.api.v1.system_health import router as system_health_router
from app.api.v1.ui_generation import router as ui_generation_router
from app.api.v1.users import router as users_router
from app.api.v1.websocket import router as ws_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(billing_router)
api_router.include_router(calibration_router)
api_router.include_router(projects_router)
api_router.include_router(project_overview_router)
api_router.include_router(decisions_router)
api_router.include_router(experiments_router)
api_router.include_router(outcomes_router)
api_router.include_router(reports_router)
api_router.include_router(share_router)
api_router.include_router(simulations_router)
api_router.include_router(users_router)
api_router.include_router(ui_generation_router)
api_router.include_router(hardware_router)
api_router.include_router(ws_router)
api_router.include_router(analytics_router)
api_router.include_router(assumption_evidence_router)
api_router.include_router(system_health_router)
api_router.include_router(simulation_webhooks_router)
