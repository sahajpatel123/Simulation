from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "thecee",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.simulation_tasks",
        "app.tasks.stress_test_tasks",
        "app.tasks.decision_tasks",
        "app.tasks.calibration_tasks",
        "app.tasks.ui_simulation_tasks",
        "app.tasks.hardware_tasks",
        "app.tasks.hardware_consumer_simulation",
        "app.tasks.retention_email_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    worker_prefetch_multiplier=1,
    # Recycle workers to cap RSS growth on long sim runs (value is KiB; ~400 MB).
    worker_max_memory_per_child=400_000,
    worker_max_tasks_per_child=10,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    **getattr(celery_app.conf, "beat_schedule", {}),
    "week4-retention-emails": {
        "task": "retention.send_week4_retention_emails",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
}

# Register beat task modules on import (CLI / assert checks)
import app.tasks.retention_email_tasks  # noqa: E402, F401


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs) -> None:
    from app.tasks.calibration_tasks import (
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
