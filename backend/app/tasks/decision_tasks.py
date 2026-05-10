from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from celery import Task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.assumption import Assumption
from app.models.decision import Decision
from app.models.environment import Environment
from app.models.project import Project
from app.simulation.aggregation import ResultsAggregator
from app.simulation.funnel import FunnelExecutionEngine
from app.simulation.profiles import AgentProfileGenerator
from app.worker import celery_app

logger = logging.getLogger(__name__)

SCENARIO_AGENT_VOLUME: int = 5000
BASE_SEED: int = 3131
SURVIVAL_THRESHOLD: float = 0.05


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionTask(Task):
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


def _merge_env_params(
    base_env_params: dict[str, Any],
    scenario_params: dict[str, Any],
) -> dict[str, Any]:
    merged = base_env_params.copy()
    numeric_fields = {
        "price_point",
        "price_sensitivity",
        "market_maturity",
        "growth_rate_per_month",
        "consumer_volume",
    }
    for field, value in scenario_params.items():
        if field in numeric_fields and value is not None:
            if field == "price_point":
                merged["average_order_value"] = float(value)
            else:
                merged[field] = value
    return merged


def _build_key_insights(
    scenario_results: list[dict[str, Any]],
    recommended: str,
    winner_margin: float,
) -> list[str]:
    insights: list[str] = []

    if not scenario_results:
        return insights

    best = max(scenario_results, key=lambda s: s["conversion_rate"])
    worst = min(scenario_results, key=lambda s: s["conversion_rate"])

    insights.append(
        f"{best['scenario_name']} leads with {best['conversion_rate']:.1%} conversion "
        f"vs {worst['scenario_name']} at {worst['conversion_rate']:.1%}."
    )

    if winner_margin > 0.05:
        insights.append(
            f"The margin is significant ({winner_margin:.1%}) — "
            f"{recommended} is a clear winner, not a marginal one."
        )
    elif winner_margin < 0.01:
        insights.append(
            "All scenarios perform similarly — the decision is low-risk. "
            "Choose based on execution feasibility, not conversion delta."
        )

    kill_shots = [s for s in scenario_results if s["conversion_rate"] < 0.01]
    if kill_shots:
        names = ", ".join(s["scenario_name"] for s in kill_shots)
        insights.append(
            f"Warning: {names} produced near-zero conversion. "
            "These scenarios should be discarded before any real-world test."
        )

    high_conf = [s for s in scenario_results if s["confidence_score"] >= 70]
    if len(high_conf) == len(scenario_results):
        insights.append(
            "All scenarios have high confidence scores — results are stable "
            "and unlikely to change significantly with more simulation runs."
        )

    return insights


@celery_app.task(
    name="decision.run_single_scenario",
    soft_time_limit=480,
    time_limit=540,
)
def run_single_scenario(
    project_id: int,
    scenario: dict[str, Any],
    base_env_params: dict[str, Any],
    assumption_dicts: list[dict[str, Any]],
    seed_offset: int,
) -> dict[str, Any]:
    scenario_name = scenario.get("name", "Unnamed")
    logger.info("[Decision] Running scenario '%s' project_id=%s", scenario_name, project_id)

    try:
        env_params = _merge_env_params(base_env_params, scenario.get("parameters", {}))

        generator = AgentProfileGenerator()
        agents = generator.generate_population(
            volume=SCENARIO_AGENT_VOLUME,
            env_params=env_params,
            scenario_type=None,
            seed=BASE_SEED + seed_offset,
        )

        engine = FunnelExecutionEngine(num_workers=1, store_paths=False)
        funnel = engine.run_batch(
            agents=agents,
            env_params=env_params,
            assumptions=assumption_dicts,
            seed=BASE_SEED + seed_offset,
        )

        aggregator = ResultsAggregator()
        agg = aggregator.aggregate(
            [funnel],
            base_price=float(env_params.get("average_order_value", 999.0)),
            price_sensitivity=float(env_params.get("price_sensitivity", 0.55)),
        )

        survival_prob = min(1.0, round(funnel.conversion_rate / SURVIVAL_THRESHOLD, 3))

        return {
            "scenario_name": scenario_name,
            "scenario_description": scenario.get("description", ""),
            "parameters_used": env_params,
            "conversion_rate": agg.mean_conversion_rate,
            "ci_low": agg.ci_95.low,
            "ci_high": agg.ci_95.high,
            "revenue_projection": agg.mean_revenue,
            "survival_probability": survival_prob,
            "confidence_score": agg.confidence_score,
            "worst_drop_off_stage": agg.worst_drop_off_stage,
            "error": None,
        }

    except Exception as exc:
        logger.exception("[Decision] Scenario '%s' failed", scenario_name)
        return {
            "scenario_name": scenario_name,
            "scenario_description": scenario.get("description", ""),
            "parameters_used": {},
            "conversion_rate": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "revenue_projection": 0.0,
            "survival_probability": 0.0,
            "confidence_score": 0,
            "worst_drop_off_stage": "UNKNOWN",
            "error": str(exc),
        }


@celery_app.task(
    bind=True,
    base=DecisionTask,
    name="decision.run_decision_comparison",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=900,
    time_limit=960,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_decision_comparison(self, decision_id: int) -> dict[str, Any]:
    logger.info("[Decision] Orchestrator started — decision_id=%s", decision_id)

    decision: Decision | None = None

    try:
        decision = self.db.query(Decision).filter(Decision.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        decision.status = "RUNNING"
        decision.task_id = self.request.id
        self.db.commit()

        project = self.db.query(Project).filter(Project.id == decision.project_id).first()
        if not project:
            raise ValueError(f"Project {decision.project_id} not found")

        environment = (
            self.db.query(Environment).filter(Environment.project_id == decision.project_id).first()
        )
        if not environment:
            raise ValueError("No environment configured")

        assumptions = (
            self.db.query(Assumption).filter(Assumption.project_id == decision.project_id).all()
        )

        base_env_params = environment.manual_params_json or {
            "consumer_volume": SCENARIO_AGENT_VOLUME,
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

        scenarios = (decision.results_json or {}).get("scenarios_input", [])
        if len(scenarios) < 2:
            raise ValueError("Decision requires at least 2 scenarios")

        logger.info("[Decision] Dispatching %s scenarios decision_id=%s", len(scenarios), decision_id)

        raw_results: list[dict[str, Any]] = [
            run_single_scenario.run(
                project_id=decision.project_id,
                scenario=scenario,
                base_env_params=base_env_params,
                assumption_dicts=assumption_dicts,
                seed_offset=index * 100,
            )
            for index, scenario in enumerate(scenarios)
        ]

        valid = [result for result in raw_results if not result.get("error")]
        failed = [result for result in raw_results if result.get("error")]

        for failed_scenario in failed:
            logger.warning(
                "[Decision] Scenario '%s' failed: %s",
                failed_scenario["scenario_name"],
                failed_scenario["error"],
            )

        if not valid:
            raise ValueError("All scenario simulations failed")

        valid.sort(key=lambda result: result["conversion_rate"], reverse=True)
        for rank, result in enumerate(valid, start=1):
            result["rank"] = rank

        recommended = valid[0]["scenario_name"]
        best_conv = valid[0]["conversion_rate"]
        second_conv = valid[1]["conversion_rate"] if len(valid) > 1 else best_conv
        winner_margin = round(best_conv - second_conv, 4)
        key_insights = _build_key_insights(valid, recommended, winner_margin)

        results_data = {
            "title": decision.title,
            "description": decision.description,
            "status": "COMPLETED",
            "scenarios": valid,
            "recommended_scenario": recommended,
            "winner_margin": winner_margin,
            "key_insights": key_insights,
            "scenarios_input": scenarios,
            "generated_at": _utcnow(),
            "task_id": self.request.id,
        }

        decision.status = "COMPLETED"
        decision.results_json = results_data
        self.db.commit()

        logger.info(
            "[Decision] Complete — decision_id=%s winner='%s' margin=%.4f",
            decision_id,
            recommended,
            winner_margin,
        )
        return results_data

    except Exception as exc:
        logger.exception("[Decision] Failed — decision_id=%s", decision_id)
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if decision is not None and retries >= max_retries:
            try:
                decision.status = "FAILED"
                decision.error_message = (
                    f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()[:1000]}"
                )
                self.db.commit()
            except Exception as _exc:
                logger.debug(
                    "%s suppressed: %s",
                    __name__,
                    _exc,
                )
        raise self.retry(exc=exc)
