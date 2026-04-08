import logging
import time

from celery import Task

from app.core.database import SessionLocal
from app.worker import celery_app

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """
    Base task class that provides a DB session lifecycle.
    Subclass this for any task that needs database access.
    Ensures the session is always closed after task completion
    regardless of success or failure.
    """

    _db = None

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="simulation.run_full_simulation",
    max_retries=2,
    default_retry_delay=30,
)
def run_full_simulation(self, project_id: int, simulation_id: int):
    """
    Main simulation task. Placeholder until Step 22.
    Demonstrates the full lifecycle: start -> progress -> complete.
    The simulation engine (Steps 21a-d) will replace the sleep.
    """

    logger.info(
        f"[Simulation] Starting - project_id={project_id} simulation_id={simulation_id}"
    )

    try:
        from app.models.simulation import Simulation

        sim = self.db.query(Simulation).filter(Simulation.id == simulation_id).first()

        if not sim:
            logger.error(f"Simulation {simulation_id} not found in DB")
            return {"status": "FAILED", "error": "Simulation record not found"}

        sim.status = "RUNNING"
        self.db.commit()

        for i in range(5):
            time.sleep(1)
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": (i + 1) * 20,
                    "total": 100,
                    "stage": f"Processing batch {i + 1}/5",
                    "agents_processed": (i + 1) * 2000,
                },
            )
            logger.info(
                f"[Simulation] Progress {(i + 1) * 20}% - simulation_id={simulation_id}"
            )

        sim.status = "COMPLETED"
        sim.results_json = '{"placeholder": true, "conversion_rate": 0.193}'
        self.db.commit()

        logger.info(f"[Simulation] Completed - simulation_id={simulation_id}")
        return {
            "status": "COMPLETED",
            "simulation_id": simulation_id,
            "project_id": project_id,
        }

    except Exception as exc:
        logger.exception(
            f"[Simulation] Failed - simulation_id={simulation_id} error={exc}"
        )

        try:
            from app.models.simulation import Simulation

            sim = self.db.query(Simulation).filter(Simulation.id == simulation_id).first()
            if sim:
                sim.status = "FAILED"
                self.db.commit()
        except Exception:
            pass

        raise self.retry(exc=exc)


@celery_app.task(name="simulation.health_check")
def health_check():
    """Lightweight task to verify the worker is reachable."""

    return {"status": "ok", "worker": "reachable"}
