from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from celery import Task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.simulation.funnel import FunnelExecutionEngine, FunnelResult
from app.simulation.profiles import AgentProfileGenerator
from app.worker import celery_app

logger = logging.getLogger(__name__)


class SimulationTask(Task):
    abstract = True
    _db: Session | None = None

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs) -> None:
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mark_failed(db: Session, sim: Simulation, exc: Exception) -> None:
    try:
        tb = traceback.format_exc()
        msg = f"{type(exc).__name__}: {str(exc)}\n{tb}"
        sim.status = "FAILED"
        sim.error_message = msg[:2000]
        sim.updated_at = _utcnow()
        db.commit()
    except Exception as inner:
        logger.error(f"[Simulation] Could not persist FAILED status: {inner}")
        try:
            db.rollback()
        except Exception:
            pass


def _serialise_result(result: FunnelResult) -> dict:
    return {
        "total_agents": result.total_agents,
        "converted": result.converted,
        "conversion_rate": result.conversion_rate,
        "ci_low": result.ci_low,
        "ci_high": result.ci_high,
        "revenue_projection": result.revenue_projection,
        "avg_time_seconds": result.avg_time_seconds,
        "wall_time_seconds": result.wall_time_seconds,
        "agents_per_second": result.agents_per_second,
        "seed_used": result.seed_used,
        "stage_counts": result.stage_counts,
        "stage_metrics": [
            {
                "state": sm.state,
                "agent_count": sm.agent_count,
                "entry_rate": sm.entry_rate,
                "drop_off_rate": sm.drop_off_rate,
                "avg_time_seconds": sm.avg_time_seconds,
            }
            for sm in result.stage_metrics
        ],
        "demographics": {
            "by_income_bracket": result.demographics.by_income_bracket,
            "by_region": result.demographics.by_region,
            "by_device": result.demographics.by_device,
            "by_age_bracket": result.demographics.by_age_bracket,
        },
        "sample_paths": result.sample_paths[:10],
        "completed_at": _utcnow().isoformat(),
    }


@celery_app.task(
    bind=True,
    base=SimulationTask,
    name="simulation.run_full_simulation",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=540,
    time_limit=600,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_full_simulation(self, simulation_id: int) -> dict:
    logger.info(
        f"[Simulation] Task started - simulation_id={simulation_id} task_id={self.request.id}"
    )

    sim: Simulation | None = None

    try:
        sim = self.db.query(Simulation).filter(Simulation.id == simulation_id).first()
        if not sim:
            raise ValueError(f"Simulation {simulation_id} not found in DB")

        sim.status = "RUNNING"
        sim.task_id = self.request.id
        sim.updated_at = _utcnow()
        self.db.commit()

        self.update_state(
            state="PROGRESS",
            meta={"stage": "Loading project data", "pct": 5},
        )

        project = self.db.query(Project).filter(Project.id == sim.project_id).first()
        if not project:
            raise ValueError(f"Project {sim.project_id} not found")

        environment = (
            self.db.query(Environment)
            .filter(Environment.project_id == sim.project_id)
            .first()
        )
        if not environment:
            raise ValueError(
                "No environment configured. "
                "POST /api/v1/projects/{id}/environments before running simulation."
            )

        assumptions = (
            self.db.query(Assumption)
            .filter(Assumption.project_id == sim.project_id)
            .all()
        )

        env_params = environment.manual_params_json or {
            "consumer_volume": sim.consumer_volume,
            "growth_rate_per_month": environment.growth_rate_per_month,
            "average_order_value": environment.average_order_value,
            "price_sensitivity": environment.price_sensitivity,
            "market_maturity": environment.market_maturity,
        }

        assumption_dicts = [
            {
                "id": a.id,
                "text": a.text,
                "sensitivity": a.sensitivity,
                "impact_score": a.impact_score,
                "category": a.category,
            }
            for a in assumptions
        ]

        logger.info(
            f"[Simulation] Data loaded - project_id={sim.project_id} "
            f"assumptions={len(assumption_dicts)} volume={sim.consumer_volume}"
        )

        self.update_state(
            state="PROGRESS",
            meta={"stage": "Generating agent population", "pct": 15},
        )

        generator = AgentProfileGenerator()
        agents = generator.generate_population(
            volume=sim.consumer_volume,
            env_params=env_params,
            scenario_type=environment.scenario_type,
            seed=simulation_id * 37,
        )

        logger.info(f"[Simulation] Population generated - n={len(agents)}")

        self.update_state(
            state="PROGRESS",
            meta={"stage": "Running funnel simulation", "pct": 25},
        )

        engine = FunnelExecutionEngine(
            num_workers=1,
            store_paths=True,
            max_stored_paths=50,
        )

        funnel_result: FunnelResult = engine.run_batch(
            agents=agents,
            env_params=env_params,
            assumptions=assumption_dicts,
            seed=simulation_id * 37,
        )

        logger.info(
            f"[Simulation] Funnel complete - "
            f"conversion_rate={funnel_result.conversion_rate:.3f} "
            f"converted={funnel_result.converted}/{funnel_result.total_agents} "
            f"wall={funnel_result.wall_time_seconds:.1f}s"
        )

        self.update_state(
            state="PROGRESS",
            meta={"stage": "Persisting results", "pct": 90},
        )

        results_dict = _serialise_result(funnel_result)

        sim.status = "COMPLETED"
        sim.results_json = results_dict
        sim.confidence_score = funnel_result.conversion_rate
        sim.updated_at = _utcnow()

        project.status = "SIMULATION_COMPLETE"
        project.updated_at = _utcnow()

        self.db.commit()

        logger.info(f"[Simulation] Persisted - simulation_id={simulation_id}")

        return {
            "simulation_id": simulation_id,
            "status": "COMPLETED",
            "conversion_rate": funnel_result.conversion_rate,
            "converted": funnel_result.converted,
            "total_agents": funnel_result.total_agents,
        }

    except Exception as exc:
        logger.exception(f"[Simulation] Failed - simulation_id={simulation_id}")
        if sim is not None:
            _mark_failed(self.db, sim, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="simulation.health_check")
def health_check() -> dict:
    return {"status": "ok", "worker": "reachable", "ts": _utcnow().isoformat()}
