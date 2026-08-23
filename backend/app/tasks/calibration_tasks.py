from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.simulation.calibration_engine import CalibrationEngine
from app.simulation.product_type import ProductType

# codeql[py/cyclic-import]: celery_app is required at decoration time for @celery_app.task; worker.py imports task modules lazily, so the cycle never executes at runtime
from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="calibration.run_systematic_bias_update")
def run_systematic_bias_update() -> None:
    db = SessionLocal()
    eng = CalibrationEngine()
    try:
        for pt in ProductType:
            eng.update_systematic_bias(pt.value, db)
        logger.info("Systematic bias update complete")
    except Exception as e:
        logger.exception("Bias update error: %s", e)
    finally:
        db.close()


@celery_app.task(name="calibration.run_structural_pattern_update")
def run_structural_pattern_update() -> None:
    db = SessionLocal()
    eng = CalibrationEngine()
    try:
        eng.update_structural_patterns(db)
        logger.info("Structural pattern update complete")
    except Exception as e:
        logger.exception("Pattern update error: %s", e)
    finally:
        db.close()


@celery_app.task(name="calibration.run_cluster_trait_calibration")
def run_cluster_trait_calibration() -> None:
    db = SessionLocal()
    eng = CalibrationEngine()
    try:
        eng.update_cluster_trait_calibration(db)
        logger.info("Cluster trait calibration complete")
    except Exception as e:
        logger.exception("Cluster trait calibration error: %s", e)
    finally:
        db.close()


@celery_app.task(name="calibration.run_funnel_stage_calibration")
def run_funnel_stage_calibration() -> None:
    """Learn per-stage funnel corrections from validated founder outcomes."""
    db = SessionLocal()
    eng = CalibrationEngine()
    try:
        eng.update_funnel_stage_calibration(db)
        logger.info("Funnel stage calibration update complete")
    except Exception as e:
        logger.exception("Funnel stage calibration error: %s", e)
    finally:
        db.close()
