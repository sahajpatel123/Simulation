from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from celery import Task
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.simulation.aggregation import ResultsAggregator
from app.simulation.funnel import FunnelExecutionEngine
from app.simulation.profiles import AgentProfileGenerator
from app.worker import celery_app

logger = logging.getLogger(__name__)

STRESS_MULTIPLIER: float = 1.9
KILL_SHOT_THRESHOLD: float = 0.01
AGENT_VOLUME: int = 5000
BASE_SEED: int = 7777


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StressTask(Task):
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
            except Exception as _exc:
                logger.debug(
                    "%s suppressed: %s",
                    __name__,
                    _exc,
                )
            self._db = None


def _build_assumption_dicts(
    assumptions: list[Assumption],
    stressed_id: int | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for assumption in assumptions:
        score = assumption.impact_score
        if stressed_id is not None and assumption.id == stressed_id:
            score = min(10.0, score * STRESS_MULTIPLIER)
        result.append(
            {
                "id": assumption.id,
                "text": assumption.text,
                "sensitivity": assumption.sensitivity,
                "impact_score": score,
                "category": assumption.category,
            }
        )
    return result


def _kill_shot_probability(delta: float, sensitivity: str) -> float:
    sev_weights = {"CRITICAL": 1.0, "HIGH": 0.7, "MEDIUM": 0.4, "LOW": 0.15}
    sev_w = sev_weights.get(sensitivity.upper(), 0.4)
    magnitude = min(1.0, abs(delta) * 25)
    return round(magnitude * sev_w, 3)


def _overall_risk(sensitivity_matrix: list[dict[str, Any]]) -> str:
    if not sensitivity_matrix:
        return "LOW"
    worst_delta = min(row["delta"] for row in sensitivity_matrix)
    kill_shots = sum(1 for row in sensitivity_matrix if row["kill_shot"])

    if worst_delta < -0.030 or kill_shots >= 2:
        return "CRITICAL"
    if worst_delta < -0.018 or kill_shots == 1:
        return "HIGH"
    if worst_delta < -0.008:
        return "MEDIUM"
    return "LOW"


def _recommendation(
    assumption_text: str,
    sensitivity: str,
    delta: float,
    kill_shot: bool,
) -> str:
    severity_prefix = {
        "CRITICAL": "Validate before any investment:",
        "HIGH": "De-risk before launch:",
        "MEDIUM": "Monitor closely post-launch:",
    }.get(sensitivity.upper(), "Monitor:")

    if kill_shot:
        return (
            f"{severity_prefix} This assumption alone can collapse conversion. "
            "Run a real-world micro-test (e.g. landing page A/B, 50 user interviews) "
            f"specifically targeting: \"{assumption_text[:80]}\""
        )
    if delta < -0.015:
        return (
            f"{severity_prefix} Stress on this assumption reduces conversion by {abs(delta):.1%}. "
            f"Build a contingency plan if \"{assumption_text[:60]}\" proves false."
        )
    return (
        f"{severity_prefix} Low but non-zero risk. "
        f"Track \"{assumption_text[:60]}\" as a KPI metric from day one."
    )


@celery_app.task(
    bind=True,
    base=StressTask,
    name="stress_test.run_assumption_stress_test",
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=840,
    time_limit=900,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_assumption_stress_test(self, project_id: int) -> dict[str, Any]:
    logger.info("[StressTest] Started — project_id=%s task_id=%s", project_id, self.request.id)

    project: Project | None = None

    try:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        self.db.execute(
            text("UPDATE projects SET stress_test_json = :v WHERE id = :id"),
            {"v": json.dumps({"status": "RUNNING", "task_id": self.request.id}), "id": project_id},
        )
        self.db.commit()

        environment = (
            self.db.query(Environment).filter(Environment.project_id == project_id).first()
        )
        if not environment:
            raise ValueError("No environment configured")

        target_assumptions = (
            self.db.query(Assumption)
            .filter(
                Assumption.project_id == project_id,
                Assumption.sensitivity.in_(["CRITICAL", "HIGH"]),
            )
            .order_by(Assumption.impact_score.desc())
            .all()
        )

        if not target_assumptions:
            result = {
                "status": "COMPLETED",
                "sensitivity_matrix": [],
                "kill_shots": [],
                "overall_risk_level": "LOW",
                "baseline_conversion": 0.0,
                "assumptions_tested": 0,
                "message": "No CRITICAL or HIGH assumptions found — nothing to stress test",
                "generated_at": _utcnow(),
                "task_id": self.request.id,
            }
            self.db.execute(
                text("UPDATE projects SET stress_test_json = :v WHERE id = :id"),
                {"v": json.dumps(result), "id": project_id},
            )
            self.db.commit()
            return result

        env_params = environment.manual_params_json or {
            "consumer_volume": AGENT_VOLUME,
            "growth_rate_per_month": environment.growth_rate_per_month,
            "average_order_value": environment.average_order_value,
            "price_sensitivity": environment.price_sensitivity,
            "market_maturity": environment.market_maturity,
        }

        generator = AgentProfileGenerator()
        agents = generator.generate_population(
            volume=AGENT_VOLUME,
            env_params=env_params,
            scenario_type=environment.scenario_type,
            seed=BASE_SEED,
        )

        engine = FunnelExecutionEngine(num_workers=1, store_paths=False)
        aggregator = ResultsAggregator()

        logger.info("[StressTest] Running baseline — project_id=%s", project_id)
        baseline_funnel = engine.run_batch(
            agents=agents,
            env_params=env_params,
            assumptions=_build_assumption_dicts(target_assumptions, stressed_id=None),
            seed=BASE_SEED,
        )
        baseline_agg = aggregator.aggregate(
            [baseline_funnel],
            base_price=float(env_params.get("average_order_value", 999.0)),
            price_sensitivity=float(env_params.get("price_sensitivity", 0.55)),
        )
        baseline_conv = baseline_agg.mean_conversion_rate

        sensitivity_matrix: list[dict[str, Any]] = []

        for idx, assumption in enumerate(target_assumptions, start=1):
            logger.info(
                "[StressTest] Stressing assumption %s/%s: id=%s sensitivity=%s",
                idx,
                len(target_assumptions),
                assumption.id,
                assumption.sensitivity,
            )

            stressed_funnel = engine.run_batch(
                agents=agents,
                env_params=env_params,
                assumptions=_build_assumption_dicts(target_assumptions, stressed_id=assumption.id),
                seed=BASE_SEED + assumption.id,
            )
            stressed_agg = aggregator.aggregate(
                [stressed_funnel],
                base_price=float(env_params.get("average_order_value", 999.0)),
                price_sensitivity=float(env_params.get("price_sensitivity", 0.55)),
            )
            stressed_conv = stressed_agg.mean_conversion_rate
            delta = stressed_conv - baseline_conv
            delta_pct = (delta / baseline_conv * 100.0) if baseline_conv > 0 else 0.0
            kill_shot = stressed_conv < KILL_SHOT_THRESHOLD

            sensitivity_matrix.append(
                {
                    "assumption_id": assumption.id,
                    "assumption_text": assumption.text,
                    "sensitivity": assumption.sensitivity,
                    "baseline_conversion": round(baseline_conv, 4),
                    "stressed_conversion": round(stressed_conv, 4),
                    "delta": round(delta, 4),
                    "delta_pct": round(delta_pct, 2),
                    "kill_shot": kill_shot,
                    "kill_shot_prob": _kill_shot_probability(delta, assumption.sensitivity),
                    "recommendation": _recommendation(
                        assumption.text, assumption.sensitivity, delta, kill_shot
                    ),
                }
            )

        sensitivity_matrix.sort(key=lambda row: row["delta"])
        kill_shots = [row for row in sensitivity_matrix if row["kill_shot"]]
        overall_risk = _overall_risk(sensitivity_matrix)

        final_result = {
            "status": "COMPLETED",
            "sensitivity_matrix": sensitivity_matrix,
            "kill_shots": kill_shots,
            "overall_risk_level": overall_risk,
            "baseline_conversion": baseline_conv,
            "assumptions_tested": len(sensitivity_matrix),
            "generated_at": _utcnow(),
            "task_id": self.request.id,
        }

        self.db.execute(
            text("UPDATE projects SET stress_test_json = :v WHERE id = :id"),
            {"v": json.dumps(final_result), "id": project_id},
        )
        self.db.commit()

        logger.info(
            "[StressTest] Complete — project_id=%s tested=%s kill_shots=%s risk=%s",
            project_id,
            len(sensitivity_matrix),
            len(kill_shots),
            overall_risk,
        )
        return final_result

    except Exception as exc:
        logger.exception("[StressTest] Failed — project_id=%s", project_id)
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if project and retries >= max_retries:
            error_payload = {
                "status": "FAILED",
                "error": str(exc),
                "traceback": traceback.format_exc()[:1000],
                "generated_at": _utcnow(),
                "task_id": self.request.id if getattr(self, "request", None) else None,
            }
            try:
                self.db.execute(
                    text("UPDATE projects SET stress_test_json = :v WHERE id = :id"),
                    {"v": json.dumps(error_payload), "id": project_id},
                )
                self.db.commit()
            except Exception as _exc:
                logger.debug(
                    "%s suppressed: %s",
                    __name__,
                    _exc,
                )
        raise self.retry(exc=exc)
