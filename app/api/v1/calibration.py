from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.simulation.calibration import CalibrationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


@router.get(
    "/",
    response_model=dict,
    summary="Platform-wide calibration accuracy metrics",
)
def get_platform_calibration(
    db: Session = Depends(get_db),
):
    engine = CalibrationEngine()
    metrics = engine.calculate_platform_accuracy(db)
    return {
        "platform_accuracy": metrics.platform_accuracy,
        "total_outcomes": metrics.total_outcomes,
        "total_projects_with_data": metrics.total_projects_with_data,
        "maturity_score": metrics.maturity_score,
        "calibration_trend": metrics.calibration_trend,
        "trend_delta": metrics.trend_delta,
        "data_sufficient": metrics.data_sufficient,
        "last_computed_at": metrics.last_computed_at,
        "category_accuracy": [asdict(category) for category in metrics.category_accuracy],
        "markov_adjustments": [asdict(adj) for adj in metrics.markov_adjustments],
        "sampling_adjustments": [asdict(adj) for adj in metrics.sampling_adjustments],
    }


@router.post(
    "/apply-adjustments",
    summary="Apply Markov prior adjustments from latest outcomes",
    responses=_JSON_200,
)
def apply_markov_adjustments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    engine = CalibrationEngine()
    metrics = engine.update_markov_priors(db)
    return {
        "applied": len(metrics.markov_adjustments),
        "platform_accuracy": metrics.platform_accuracy,
        "data_sufficient": metrics.data_sufficient,
        "adjustments_made": [
            {
                "transition": f"{adj.from_state} → {adj.to_state}",
                "delta": adj.delta,
                "rationale": adj.rationale,
            }
            for adj in metrics.markov_adjustments
        ],
    }
