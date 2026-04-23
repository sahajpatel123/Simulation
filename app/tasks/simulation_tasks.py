from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from celery import Task
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.tier_enforcement import enforce_simulation_limit, increment_simulation_count
from app.core.websocket import sync_broadcast
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.simulation.accountability import AccountabilityEngine
from app.simulation.aggregation import ResultsAggregator
from app.simulation.conductor import Conductor, ConductorResult
from app.simulation.funnel import (
    DemographicBreakdown,
    FunnelResult,
    StageMetrics,
)
from app.simulation.markov import STATES
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
    msg = str(exc)[:500]
    sync_broadcast(sim.id, "FAILED", "Error", 0, extra={"error": msg})
    try:
        db.execute(
            text(
                """
                UPDATE simulations
                SET status = 'FAILED', error_message = :msg, updated_at = :u
                WHERE id = :sid
                """
            ),
            {"msg": msg, "u": _utcnow(), "sid": sim.id},
        )
        sim.status = "FAILED"
        sim.error_message = msg
        sim.updated_at = _utcnow()
        db.commit()
    except Exception as inner:
        logger.error(f"[Simulation] Could not persist FAILED status: {inner}")
        try:
            db.rollback()
        except Exception:
            pass


def _funnel_result_from_conductor(
    conductor_result: ConductorResult,
    total_agents: int,
    env_params: dict,
    seed: int,
    wall_time_seconds: float,
) -> FunnelResult:
    """Build a FunnelResult aligned with conductor PWC so ResultsAggregator can run."""
    pwc = float(conductor_result.population_weighted_conversion)
    pwc = max(0.001, min(0.99, pwc))
    converted = int(round(pwc * total_agents)) if total_agents else 0
    aov = float(env_params.get("average_order_value", 999.0))
    revenue = float(converted * aov)
    eps = max(0.001, pwc * 0.05)

    n = total_agents
    stage_counts = {
        "ARRIVE": n,
        "BROWSE": max(converted, int(n * 0.88)) if n else 0,
        "CONSIDER": max(converted, int(n * 0.62)) if n else 0,
        "DECIDE": max(converted, int(n * 0.42)) if n else 0,
        "PURCHASE": converted,
        "ABANDON": max(0, n - converted),
        "RETURN": max(0, min(n // 50, n)) if n else 0,
    }

    ordered_stages = [s.value for s in STATES]
    stage_metrics: list[StageMetrics] = []
    prev_count = n
    for stage in ordered_stages:
        count = stage_counts.get(stage, 0)
        entry_r = count / n if n > 0 else 0.0
        raw_dropoff = 1.0 - (count / prev_count) if prev_count > 0 else 0.0
        dropoff_r = max(0.0, min(1.0, raw_dropoff))
        stage_metrics.append(
            StageMetrics(
                state=stage,
                agent_count=count,
                entry_rate=round(entry_r, 4),
                drop_off_rate=round(dropoff_r, 4),
                avg_time_seconds=30.0,
            )
        )
        prev_count = max(1, count)

    return FunnelResult(
        total_agents=n,
        converted=converted,
        conversion_rate=pwc,
        avg_time_seconds=120.0,
        revenue_projection=revenue,
        ci_low=max(0.0, pwc - eps),
        ci_high=min(1.0, pwc + eps),
        stage_metrics=stage_metrics,
        stage_counts=stage_counts,
        demographics=DemographicBreakdown(
            by_income_bracket={},
            by_region={},
            by_device={},
            by_age_bracket={},
        ),
        wall_time_seconds=max(wall_time_seconds, 0.001),
        agents_per_second=n / max(wall_time_seconds, 0.001),
        seed_used=seed,
        sample_paths=[],
    )


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

        project = self.db.query(Project).filter(Project.id == sim.project_id).first()
        if not project:
            raise ValueError(f"Project {sim.project_id} not found")

        user = self.db.query(User).filter(User.id == project.user_id).first()
        if not user:
            raise ValueError(f"User for project {sim.project_id} not found")
        enforce_simulation_limit(user, self.db)

        sim.status = "RUNNING"
        sim.task_id = self.request.id
        sim.updated_at = _utcnow()
        self.db.commit()

        self.update_state(state="PROGRESS", meta={"stage": "Loading project data", "pct": 5})
        sync_broadcast(simulation_id, "RUNNING", "Loading project data", 5)

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

        base_env = environment.manual_params_json or {
            "consumer_volume": sim.consumer_volume,
            "growth_rate_per_month": environment.growth_rate_per_month,
            "average_order_value": environment.average_order_value,
            "price_sensitivity": environment.price_sensitivity,
            "market_maturity": environment.market_maturity,
        }
        env_params = {**base_env, "description": project.description or ""}

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

        self.update_state(state="PROGRESS", meta={"stage": "Generating agent population", "pct": 15})
        sync_broadcast(simulation_id, "RUNNING", "Generating agent population", 15)

        generator = AgentProfileGenerator()
        agents = generator.generate_population(
            volume=sim.consumer_volume,
            env_params=env_params,
            scenario_type=environment.scenario_type,
            seed=simulation_id * 37,
        )

        logger.info(f"[Simulation] Population generated - n={len(agents)}")

        self.update_state(state="PROGRESS", meta={"stage": "Running cluster simulation", "pct": 25})
        sync_broadcast(simulation_id, "RUNNING", "Running cluster simulation", 25, 0, sim.consumer_volume)

        seed = simulation_id * 37
        conductor = Conductor()
        product_type = conductor.detect_product_type(
            project.description or "",
            assumption_dicts,
        )
        t0 = time.perf_counter()
        conductor_result = conductor.run(
            agents=agents,
            env_params=env_params,
            assumptions=assumption_dicts,
            product_type=product_type,
            simulation_id=simulation_id,
            signal_quality=sim.signal_quality or 0.0,
            db=self.db,
            simulation=sim,
            user_id=project.user_id,
        )
        wall_s = time.perf_counter() - t0

        accountability = AccountabilityEngine()
        ranked = accountability.generate_domain_findings(
            conductor_result,
            total_agents=len(agents),
        )
        hv_name, hv_cr = accountability.highest_value_cluster(conductor_result)

        funnel_result = _funnel_result_from_conductor(
            conductor_result,
            total_agents=len(agents),
            env_params=env_params,
            seed=seed,
            wall_time_seconds=wall_s,
        )

        logger.info(
            f"[Simulation] Conductor complete - "
            f"conversion_rate={funnel_result.conversion_rate:.3f} "
            f"converted={funnel_result.converted}/{funnel_result.total_agents} "
            f"wall={wall_s:.1f}s product_type={product_type.value}"
        )

        self.update_state(state="PROGRESS", meta={"stage": "Persisting results", "pct": 90})
        sync_broadcast(
            simulation_id,
            "RUNNING",
            "Persisting results",
            90,
            funnel_result.total_agents,
            sim.consumer_volume,
        )

        aggregator = ResultsAggregator()
        agg_result = aggregator.aggregate(
            results=[funnel_result],
            base_price=float(env_params.get("average_order_value", 999.0)),
            price_sensitivity=float(env_params.get("price_sensitivity", 0.55)),
        )
        results_dict = aggregator.to_dict(agg_result)
        results_dict["raw_funnel"] = _serialise_result(funnel_result)
        results_dict["cluster_breakdown"] = conductor_result.cluster_breakdown
        results_dict["domain_findings"] = [f.to_dict() for f in ranked[:10]]
        results_dict["primary_failure_domain"] = accountability.primary_failure_domain(ranked)
        results_dict["highest_value_cluster"] = {
            "name": hv_name,
            "conversion_rate": hv_cr,
        }
        results_dict["architect_accountability"] = conductor_result.architect_accountability
        results_dict["product_type_detected"] = product_type.value
        results_dict["cluster_narrative"] = accountability.generate_cluster_breakdown_narrative(
            conductor_result
        )

        sim.status = "COMPLETED"
        sim.results_json = results_dict
        sim.confidence_score = float(agg_result.confidence_score) / 100.0
        sim.updated_at = _utcnow()

        project.status = "SIMULATION_COMPLETE"
        project.updated_at = _utcnow()

        self.db.commit()
        increment_simulation_count(project.user_id, self.db)
        sync_broadcast(
            simulation_id,
            "COMPLETED",
            "Done",
            100,
            funnel_result.total_agents,
            sim.consumer_volume,
            extra={"conversion_rate": funnel_result.conversion_rate},
        )

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
