"""Celery worker entrypoint (``celery -A app.worker:celery_app``).

The application instance itself lives in the neutral ``app.core.celery_app``
module so task modules never import this file — that is what keeps the
worker↔tasks import graph acyclic. This module only adds the periodic-task
registrations that need live task objects, importing them lazily inside the
signal handler (the canonical Celery pattern).
"""

from celery.schedules import crontab

from app.core.celery_app import celery_app

__all__ = ["celery_app"]


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs) -> None:
    from app.tasks.calibration_tasks import (
        run_cluster_trait_calibration,
        run_funnel_stage_calibration,
        run_structural_pattern_update,
        run_systematic_bias_update,
    )

    sender.add_periodic_task(
        crontab(day_of_week=1, hour=3),
        run_systematic_bias_update.s(),
        name="weekly-bias-correction",
    )
    sender.add_periodic_task(
        crontab(day_of_month=1, hour=4),
        run_structural_pattern_update.s(),
        name="monthly-pattern-correction",
    )
    sender.add_periodic_task(
        crontab(day_of_week=1, hour=5),
        run_cluster_trait_calibration.s(),
        name="weekly-cluster-trait-calibration",
    )
    sender.add_periodic_task(
        crontab(day_of_week=1, hour=6),
        run_funnel_stage_calibration.s(),
        name="weekly-funnel-stage-calibration",
    )
