from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from celery import Task
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.metrics import metrics
from app.core.tier_enforcement import enforce_simulation_limit, increment_simulation_count
from app.core.websocket import sync_broadcast
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.models.user import User
from app.simulation.accountability import AccountabilityEngine
from app.simulation.aggregation import ResultsAggregator
from app.simulation.cancellation import SimulationCancelled
from app.simulation.conductor import Conductor, ConductorResult
from app.simulation.funnel import (
    DemographicBreakdown,
    FunnelResult,
    StageMetrics,
)
from app.simulation.journey_analytics import serialise_per_cluster_matrices
from app.simulation.markov import STATES
from app.simulation.pipeline_timing import build_pipeline_timing
from app.simulation.profiles import AgentProfileGenerator
from app.simulation.reproducibility import stable_result_fingerprint
from app.simulation.simulation_webhook_delivery import (
    build_webhook_payload,
    deliver_webhook_event,
)
from app.simulation.webhook_delivery_history import record_webhook_delivery
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
            except Exception as _exc:
                logger.debug(
                    "%s suppressed: %s",
                    __name__,
                    _exc,
                )
            self._db = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def resolve_simulation_seed(seed: int | None, simulation_id: int) -> int:
    """Return the RNG seed a simulation run should use.

    An explicit persisted seed wins; legacy rows fall back to the
    historical ``simulation_id * 37`` scheme so pre-seed behavior is
    unchanged.
    """
    return seed if seed is not None else simulation_id * 37


def _default_base_env(consumer_volume: int, environment: Environment) -> dict:
    """The canonical full environment parameter set for a run."""
    return {
        "consumer_volume": consumer_volume,
        "growth_rate_per_month": environment.growth_rate_per_month,
        "average_order_value": environment.average_order_value,
        "price_sensitivity": environment.price_sensitivity,
        "market_maturity": environment.market_maturity,
    }


def build_environment_snapshot(
    environment: Environment,
    consumer_volume: int,
) -> dict:
    """Freeze the environment inputs a run depends on at enqueue time.

    The worker used to read the live ``environments`` row when the task
    started, so an edit made after enqueue silently changed the queued
    run. Snapshotted runs are self-contained: they reproduce the exact
    inputs the founder saw when they clicked run.
    """
    manual = environment.manual_params_json
    base_env = (
        manual
        if isinstance(manual, dict) and manual
        else _default_base_env(consumer_volume, environment)
    )
    return {
        "base_env": base_env,
        "scenario_type": environment.scenario_type,
    }


def resolve_run_environment(
    sim: Simulation,
    environment: Environment,
) -> tuple[dict, str | None]:
    """Return ``(base_env, scenario_type)`` for a simulation run.

    Prefers the frozen ``env_snapshot_json`` captured at enqueue time;
    falls back to the live environment row for legacy runs.
    """
    snapshot = (
        sim.env_snapshot_json if isinstance(sim.env_snapshot_json, dict) else None
    )
    if snapshot is not None:
        base = snapshot.get("base_env")
        if isinstance(base, dict) and base:
            return {**base}, snapshot.get("scenario_type")
        # Unusable frozen base (corrupt/empty) — fall back to the live
        # row's canonical defaults rather than running with an empty
        # env_params dict.
        return (
            _default_base_env(sim.consumer_volume, environment),
            snapshot.get("scenario_type"),
        )
    manual = environment.manual_params_json
    base_env = (
        manual
        if isinstance(manual, dict) and manual
        else _default_base_env(sim.consumer_volume, environment)
    )
    return base_env, environment.scenario_type


def _transition_count(result: object) -> int:
    """Rowcount of a terminal-state UPDATE, defaulting to 1 for fakes.

    The worker's unit-test sessions often stub ``execute()`` with a
    ``None`` result; treat that as "the transition happened" so legacy
    fakes keep exercising the notify path. Real SQLAlchemy results
    always expose ``rowcount``.
    """
    return int(getattr(result, "rowcount", 1) or 0)


def _mark_failed(
    db: Session,
    sim: Simulation,
    exc: Exception,
    *,
    pipeline_timing: dict[str, object] | None = None,
) -> None:
    """Persist a terminal FAILED state, optionally with partial run timing.

    ``pipeline_timing`` is the partial per-stage payload built from
    ``build_pipeline_timing`` at the failure site. It is stored under
    ``results_json["pipeline_timing"]`` so operators can see where a run
    died without ever touching the reproducibility fingerprint of a
    completed run.
    """
    msg = str(exc)[:500]
    failure_results_json: str | None = None
    if pipeline_timing:
        failure_results_json = json.dumps({"pipeline_timing": pipeline_timing})
    try:
        if failure_results_json is not None:
            result = db.execute(
                text(
                    """
                    UPDATE simulations
                    SET status = 'FAILED', error_message = :msg,
                        results_json = CAST(:rj AS jsonb), updated_at = :u
                    WHERE id = :sid
                      AND status IN ('QUEUED', 'RUNNING')
                    """
                ),
                {
                    "msg": msg,
                    "u": _utcnow(),
                    "sid": sim.id,
                    "rj": failure_results_json,
                },
            )
        else:
            result = db.execute(
                text(
                    """
                    UPDATE simulations
                    SET status = 'FAILED', error_message = :msg, updated_at = :u
                    WHERE id = :sid
                      AND status IN ('QUEUED', 'RUNNING')
                    """
                ),
                {"msg": msg, "u": _utcnow(), "sid": sim.id},
            )
        if _transition_count(result) == 0:
            # The row already left the cancellable states (e.g. a user
            # cancelled it). Do not overwrite that terminal state with
            # FAILED, and do not emit failure signals for it.
            db.rollback()
            return
        sim.status = "FAILED"
        sim.error_message = msg
        if pipeline_timing:
            sim.results_json = {"pipeline_timing": dict(pipeline_timing)}
        sim.updated_at = _utcnow()
        db.commit()
    except Exception as inner:
        logger.error(f"[Simulation] Could not persist FAILED status: {inner}")
        try:
            db.rollback()
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )
    metrics.sim_failed()
    sync_broadcast(sim.id, "FAILED", "Error", 0, extra={"error": msg})
    try:
        _enqueue_simulation_webhooks(
            db,
            project_id=sim.project_id,
            simulation_id=sim.id,
            status="FAILED",
            conversion_rate=None,
            error=msg,
        )
    except Exception as _exc:
        logger.debug(
            "[Simulation] webhook enqueue on failure skipped: %s",
            _exc,
        )


def _enqueue_simulation_webhooks(
    db: Session,
    *,
    project_id: int | None,
    simulation_id: int,
    status: str,
    conversion_rate: float | None,
    error: str | None,
) -> None:
    """Enqueue one Celery delivery task per ACTIVE project webhook."""
    if not project_id:
        return
    subscriptions = (
        db.query(SimulationWebhookSubscription)
        .filter(
            SimulationWebhookSubscription.project_id == project_id,
            SimulationWebhookSubscription.status == "ACTIVE",
        )
        .all()
    )
    event_type = f"simulation.{status.lower()}"
    for subscription in subscriptions:
        if subscription.event_type not in {"simulation.*", event_type}:
            continue
        deliver_simulation_webhook.delay(
            webhook_id=subscription.id,
            simulation_id=simulation_id,
            status=status,
            conversion_rate=conversion_rate,
            error=error,
        )


def _simulation_is_cancelled(db: Session, simulation_id: int) -> bool:
    """Return True when the simulation row has been marked CANCELLED.

    Uses a raw ``SELECT`` (not the ORM identity map) so a running task
    sees the API process's cancellation immediately under READ COMMITTED.
    """
    try:
        status = db.execute(
            text("SELECT status FROM simulations WHERE id = :sid"),
            {"sid": simulation_id},
        ).scalar()
    except Exception:
        # If the check itself fails, prefer finishing the run over
        # aborting it on a transient DB blip.
        return False
    return status == "CANCELLED"


def _cluster_progress_pct(completed: int, total: int) -> int:
    """Map completed/total clusters into the 25–89% band of a run.

    The conductor phase is entered at 25% and the next persisted stage
    ("Persisting results") owns 90%, so per-cluster updates stay inside
    ``[25, 89]`` regardless of how many clusters a product type evaluates.
    """
    if total <= 0 or completed <= 0:
        return 25
    raw = 25 + int(64 * completed / total)
    return max(25, min(89, raw))


def _cluster_progress_stage(cluster_id: str, completed: int, total: int) -> str:
    """Human-readable stage label for one completed cluster."""
    return f"Simulating cluster {cluster_id} ({completed}/{total})"


def _mark_cancelled(db: Session, sim: Simulation | None, simulation_id: int) -> None:
    """Persist a user-initiated cancellation and notify listeners.

    Cancellation is a terminal outcome, not a failure: no retry is
    scheduled, no FAILED row is written, and the failure counter is not
    bumped. The progress channel still hears about it. Webhook delivery
    is owned by the API cancel handler, which wins the row transition
    first — this helper only acts when it actually performed the
    transition, so a worker that observes an already-cancelled row
    cannot double-deliver notifications.
    """
    message = "Cancelled by user"
    try:
        result = db.execute(
            text(
                """
                UPDATE simulations
                SET status = 'CANCELLED',
                    error_message = COALESCE(error_message, :msg),
                    updated_at = :u
                WHERE id = :sid
                  AND status IN ('QUEUED', 'RUNNING')
                """
            ),
            {"msg": message, "u": _utcnow(), "sid": simulation_id},
        )
        if _transition_count(result) == 0:
            # The API cancel handler already moved the row to a terminal
            # state and owns the broadcast/metrics/webhook notifications.
            db.rollback()
            return
        if sim is not None:
            sim.status = "CANCELLED"
            sim.error_message = sim.error_message or message
            sim.updated_at = _utcnow()
        db.commit()
    except Exception as inner:
        logger.error(f"[Simulation] Could not persist CANCELLED status: {inner}")
        try:
            db.rollback()
        except Exception:
            pass

    metrics.sim_cancelled()
    sync_broadcast(
        simulation_id,
        "CANCELLED",
        message,
        0,
        extra={"error": message},
    )


def _derive_chain_scalars(conductor_result: ConductorResult) -> tuple[float, float, float, float]:
    """Derive population-weighted transition scalars from a ConductorResult.

    Returns (arrive_to_browse, browse_to_consider, consider_to_decide,
    decide_to_purchase) in [0, 1]. Falls back to a per-cluster conversion
    decomposition when the per-cluster override map is empty.
    """
    from app.simulation.markov import BASE_TRANSITIONS, State

    pairs = (
        (State.ARRIVE, State.BROWSE),
        (State.BROWSE, State.CONSIDER),
        (State.CONSIDER, State.DECIDE),
        (State.DECIDE, State.PURCHASE),
    )
    base = [float(BASE_TRANSITIONS[f][t]) for f, t in pairs]

    cluster_breakdown = conductor_result.cluster_breakdown or {}
    per_cluster_matrices = conductor_result.per_cluster_matrices or {}

    weighted_numer: list[float] = [0.0, 0.0, 0.0, 0.0]
    weighted_denom: float = 0.0
    for cluster_id, conversion in cluster_breakdown.items():
        overrides = per_cluster_matrices.get(cluster_id) or {}
        weight = max(0.0, float(conversion)) if conversion else 0.0
        weighted_denom += weight
        for i, (from_s, to_s) in enumerate(pairs):
            if (from_s.value, to_s.value) in overrides:
                weighted_numer[i] += weight * float(overrides[(from_s.value, to_s.value)])

    if weighted_denom <= 0.0:
        # No usable per-cluster data — fall back to the base transition
        # scalars so downstream consumers still receive a coherent chain.
        return tuple(base)

    scalars = tuple(
        max(0.0, min(1.0, numer / weighted_denom)) if weighted_denom > 0 else base[i]
        for i, numer in enumerate(weighted_numer)
    )
    return scalars  # type: ignore[return-value]


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
    arrive_to_browse, browse_to_consider, consider_to_decide, decide_to_purchase = (
        _derive_chain_scalars(conductor_result)
    )

    if n > 0:
        # Build the funnel chain top-down so counts are monotonically
        # non-increasing, then anchor PURCHASE to the conductor-derived
        # `converted` so the funnel narrative never contradicts
        # population_weighted_conversion.
        browse_count = min(n, int(round(n * arrive_to_browse)))
        consider_count = min(browse_count, int(round(browse_count * browse_to_consider)))
        decide_count = min(consider_count, int(round(consider_count * consider_to_decide)))
        # PURCHASE equals `converted` directly. Capping by decide_count
        # would silently under-report the headline conversion whenever the
        # cluster-weighted transition chain implies fewer DECIDE rows than
        # the conductor-derived population_weighted_conversion produces.
        purchase_count = converted
    else:
        browse_count = consider_count = decide_count = purchase_count = 0

    abandon_count = max(0, n - converted)
    return_count = max(0, min(n // 50, n)) if n else 0

    stage_counts = {
        "ARRIVE": n,
        "BROWSE": browse_count,
        "CONSIDER": consider_count,
        "DECIDE": decide_count,
        "PURCHASE": purchase_count,
        "ABANDON": abandon_count,
        "RETURN": return_count,
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
        # Per-stage wall-clock accounting for the persisted pipeline_timing
        # payload. Stages are recorded around the compute work only; the
        # terminal results_json write cannot time itself, so persistence is
        # intentionally excluded and the overall worker runtime is captured
        # separately as end_to_end_seconds. The first stage timer starts
        # after the RUNNING flip so end_to_end_seconds always spans at least
        # the accounted stages.
        stage_timings: dict[str, float] = {}
        active_stage = "startup"

        sim = self.db.query(Simulation).filter(Simulation.id == simulation_id).first()
        if not sim:
            raise ValueError(f"Simulation {simulation_id} not found in DB")

        if _simulation_is_cancelled(self.db, simulation_id):
            logger.info(
                f"[Simulation] Cancelled before start - simulation_id={simulation_id}"
            )
            _mark_cancelled(self.db, sim, simulation_id)
            return {"simulation_id": simulation_id, "status": "CANCELLED"}

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
        # Stash the wall-clock start so completion/failure can record a duration.
        # Stored on the instance only — not committed — so a retry gets a fresh
        # measurement rather than the original start.
        self._metrics_start = time.monotonic()
        metrics.sim_started()
        self.db.commit()

        active_stage = "load_project_data"
        _stage_t0 = time.perf_counter()
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

        base_env, scenario_type = resolve_run_environment(sim, environment)
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

        # Inject The Brief fields as structured simulation inputs
        if project.brief_positioning:
            env_params["brief_positioning"] = project.brief_positioning
            assumption_dicts.append({
                "id": -1, "text": project.brief_positioning,
                "sensitivity": "HIGH", "impact_score": 8.0,
                "category": "positioning",
            })
        if project.brief_hook:
            env_params["brief_hook"] = project.brief_hook
            assumption_dicts.append({
                "id": -2, "text": f"Homepage hook: {project.brief_hook}",
                "sensitivity": "HIGH", "impact_score": 7.0,
                "category": "hook",
            })
        if project.brief_features_json:
            import json as _json
            try:
                features = _json.loads(project.brief_features_json)
                for i, feat in enumerate(features[:3]):
                    env_params[f"brief_feature_{i}"] = feat
                    assumption_dicts.append({
                        "id": -10 - i, "text": f"Killer feature #{i + 1}: {feat}",
                        "sensitivity": "MEDIUM", "impact_score": 6.0 - i,
                        "category": "feature",
                    })
            except Exception:
                pass

        stage_timings["load_project_data"] = time.perf_counter() - _stage_t0

        logger.info(
            f"[Simulation] Data loaded - project_id={sim.project_id} "
            f"assumptions={len(assumption_dicts)} volume={sim.consumer_volume}"
        )

        self.update_state(state="PROGRESS", meta={"stage": "Generating agent population", "pct": 15})
        sync_broadcast(simulation_id, "RUNNING", "Generating agent population", 15)

        active_stage = "agent_profile_generation"
        _stage_t0 = time.perf_counter()
        generator = AgentProfileGenerator()
        agents = generator.generate_population(
            volume=sim.consumer_volume,
            env_params=env_params,
            scenario_type=scenario_type,
            seed=resolve_simulation_seed(sim.seed, simulation_id),
        )
        stage_timings["agent_profile_generation"] = time.perf_counter() - _stage_t0

        logger.info(f"[Simulation] Population generated - n={len(agents)}")

        self.update_state(state="PROGRESS", meta={"stage": "Running cluster simulation", "pct": 25})
        sync_broadcast(simulation_id, "RUNNING", "Running cluster simulation", 25, 0, sim.consumer_volume)

        seed = resolve_simulation_seed(sim.seed, simulation_id)
        conductor = Conductor()
        product_type = conductor.detect_product_type(
            project.description or "",
            assumption_dicts,
        )
        active_stage = "conductor_run"
        t0 = time.perf_counter()

        def _report_cluster_progress(
            cluster_id: str,
            completed: int,
            total: int,
        ) -> None:
            pct = _cluster_progress_pct(completed, total)
            stage = _cluster_progress_stage(cluster_id, completed, total)
            self.update_state(
                state="PROGRESS",
                meta={
                    "stage": stage,
                    "pct": pct,
                    "cluster_id": cluster_id,
                    "clusters_completed": completed,
                    "clusters_total": total,
                },
            )
            sync_broadcast(
                simulation_id,
                "RUNNING",
                stage,
                pct,
                0,
                sim.consumer_volume,
                extra={
                    "cluster_id": cluster_id,
                    "clusters_completed": completed,
                    "clusters_total": total,
                },
            )

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
            cancel_check=lambda: _simulation_is_cancelled(self.db, simulation_id),
            progress_callback=_report_cluster_progress,
        )
        wall_s = time.perf_counter() - t0
        stage_timings["conductor_run"] = wall_s

        active_stage = "accountability_and_funnel"
        _stage_t0 = time.perf_counter()
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
        stage_timings["accountability_and_funnel"] = time.perf_counter() - _stage_t0

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

        active_stage = "aggregation_and_serialization"
        _stage_t0 = time.perf_counter()
        aggregator = ResultsAggregator()
        agg_result = aggregator.aggregate(
            results=[funnel_result],
            base_price=float(env_params.get("average_order_value", 999.0)),
            price_sensitivity=float(env_params.get("price_sensitivity", 0.55)),
        )
        results_dict = aggregator.to_dict(agg_result)
        results_dict["raw_funnel"] = _serialise_result(funnel_result)
        results_dict["cluster_breakdown"] = conductor_result.cluster_breakdown
        results_dict["per_cluster_matrices"] = serialise_per_cluster_matrices(
            conductor_result.per_cluster_matrices
        )
        results_dict["cluster_weights"] = {
            cid: round(float(weight), 6)
            for cid, weight in conductor_result.cluster_weights.items()
        }
        results_dict["domain_findings"] = [f.to_dict() for f in ranked[:10]]
        results_dict["primary_failure_domain"] = accountability.primary_failure_domain(ranked)
        results_dict["seed_used"] = seed
        results_dict["highest_value_cluster"] = {
            "name": hv_name,
            "conversion_rate": hv_cr,
        }
        results_dict["architect_accountability"] = conductor_result.architect_accountability
        results_dict["product_type_detected"] = product_type.value
        results_dict["cluster_narrative"] = accountability.generate_cluster_breakdown_narrative(
            conductor_result
        )
        results_dict["conductor_diagnostics"] = conductor_result.diagnostics.to_dict()
        results_fingerprint = stable_result_fingerprint(results_dict)
        stage_timings["aggregation_and_serialization"] = time.perf_counter() - _stage_t0

        # Per-architect compute timings are volatile by nature: wall-clock
        # durations differ between identical-input replays, so they are added
        # after the fingerprint is computed and stripped by
        # VOLATILE_RESULT_KEYS during any read-back verification.
        results_dict["conductor_architect_timing"] = (
            conductor_result.diagnostics.timing_to_dict()
        )

        # Timing is volatile by nature: identical-input replays must still
        # match, so it is added after the fingerprint is computed and is
        # listed in VOLATILE_RESULT_KEYS for any read-back verification.
        results_dict["pipeline_timing"] = build_pipeline_timing(
            stage_timings,
            total_agents=len(agents),
            end_to_end_seconds=(
                time.monotonic() - self._metrics_start
                if getattr(self, "_metrics_start", None) is not None
                else None
            ),
        )

        active_stage = "persist_results"
        if _simulation_is_cancelled(self.db, simulation_id):
            logger.info(
                f"[Simulation] Cancelled before persist - simulation_id={simulation_id}"
            )
            _mark_cancelled(self.db, sim, simulation_id)
            return {"simulation_id": simulation_id, "status": "CANCELLED"}

        # Atomic terminal transition: only QUEUED/RUNNING rows may become
        # COMPLETED. If a user cancel lands between the check above and
        # this UPDATE, the guarded WHERE makes the cancel win; the loser
        # (this task) observes rowcount == 0 and unwinds as CANCELLED
        # instead of overwriting the terminal state with COMPLETED.
        transition = self.db.execute(
            update(Simulation)
            .where(
                Simulation.id == simulation_id,
                Simulation.status.in_(["QUEUED", "RUNNING"]),
            )
            .values(
                status="COMPLETED",
                results_json=results_dict,
                results_fingerprint=results_fingerprint,
                confidence_score=float(agg_result.confidence_score) / 100.0,
                updated_at=_utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        if _transition_count(transition) == 0:
            logger.info(
                f"[Simulation] Cancelled during persist - simulation_id={simulation_id}"
            )
            _mark_cancelled(self.db, sim, simulation_id)
            return {"simulation_id": simulation_id, "status": "CANCELLED"}

        sim.status = "COMPLETED"
        sim.results_json = results_dict
        sim.results_fingerprint = results_fingerprint
        sim.confidence_score = float(agg_result.confidence_score) / 100.0
        sim.updated_at = _utcnow()

        # Record end-to-end wall-clock duration for the metrics histogram.
        # ``_metrics_start`` is set right after the status flips to RUNNING;
        # fall back to a zero observation if a subclass path didn't set it.
        start = getattr(self, "_metrics_start", None)
        duration = time.monotonic() - start if start is not None else 0.0
        metrics.sim_completed(duration_seconds=duration)

        project.status = "SIMULATION_COMPLETE"
        project.updated_at = _utcnow()

        self.db.commit()
        increment_simulation_count(project.user_id, self.db)
        # Bust the cached per-project next-action so the
        # dashboard's "what should I do?" CTA reflects the
        # just-completed simulation immediately rather than
        # waiting out the TTL.
        try:
            from app.api.v1.projects import (
                _ACTIVITY_FEED_CACHE_NAMESPACE,
                _CONVERGENCE_CHECK_CACHE_NAMESPACE,
                _NEXT_ACTION_CACHE_NAMESPACE,
            )
            from app.core.response_cache import cache_invalidate

            cache_invalidate(
                namespace=_NEXT_ACTION_CACHE_NAMESPACE,
                user_id=project.user_id,
            )
            cache_invalidate(
                namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
                user_id=project.user_id,
            )
            # Convergence is computed from
            # predicted_conversion_rate across recent
            # COMPLETED sims — a new completed sim can
            # change the verdict (CONVERGED ↔ MILDLY_VARIANT
            # ↔ DIVERGED), so bust it alongside.
            cache_invalidate(
                namespace=_CONVERGENCE_CHECK_CACHE_NAMESPACE,
                user_id=project.user_id,
            )
        except Exception as _exc:
            logger.debug("next-action cache bust skipped: %s", _exc)
        sync_broadcast(
            simulation_id,
            "COMPLETED",
            "Done",
            100,
            funnel_result.total_agents,
            sim.consumer_volume,
            extra={"conversion_rate": funnel_result.conversion_rate},
        )

        try:
            _enqueue_simulation_webhooks(
                self.db,
                project_id=sim.project_id,
                simulation_id=simulation_id,
                status="COMPLETED",
                conversion_rate=funnel_result.conversion_rate,
                error=None,
            )
        except Exception as _exc:
            logger.debug(
                "[Simulation] webhook enqueue skipped: %s",
                _exc,
            )

        logger.info(f"[Simulation] Persisted - simulation_id={simulation_id}")

        return {
            "simulation_id": simulation_id,
            "status": "COMPLETED",
            "conversion_rate": funnel_result.conversion_rate,
            "converted": funnel_result.converted,
            "total_agents": funnel_result.total_agents,
        }

    except SimulationCancelled:
        logger.info(f"[Simulation] Cancelled - simulation_id={simulation_id}")
        _mark_cancelled(self.db, sim, simulation_id)
        return {"simulation_id": simulation_id, "status": "CANCELLED"}

    except Exception as exc:
        logger.exception(f"[Simulation] Failed - simulation_id={simulation_id}")
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if sim is not None and retries >= max_retries:
            # Persist the partial stage timings with the failure so an
            # operator can see how far the run got and which stage was in
            # flight when it died. This never affects the reproducibility
            # fingerprint: failed runs have no completed results_json.
            _mark_failed(
                self.db,
                sim,
                exc,
                pipeline_timing=build_pipeline_timing(
                    stage_timings,
                    total_agents=sim.consumer_volume,
                    end_to_end_seconds=(
                        time.monotonic() - self._metrics_start
                        if getattr(self, "_metrics_start", None) is not None
                        else None
                    ),
                    failed_during=active_stage,
                ),
            )
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    base=SimulationTask,
    name="simulation.deliver_webhook",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def deliver_simulation_webhook(
    self: SimulationTask,
    webhook_id: int,
    simulation_id: int,
    status: str,
    conversion_rate: float | None = None,
    error: str | None = None,
) -> dict[str, object]:
    """Deliver one signed simulation event to a subscribed endpoint."""
    subscription = (
        self.db.query(SimulationWebhookSubscription)
        .filter(SimulationWebhookSubscription.id == webhook_id)
        .first()
    )
    if subscription is None:
        return {"ok": False, "error": "subscription not found"}
    if subscription.status != "ACTIVE":
        return {"ok": False, "error": "subscription disabled"}

    payload = build_webhook_payload(
        event_type=f"simulation.{status.lower()}",
        simulation_id=simulation_id,
        project_id=subscription.project_id,
        status=status,
        conversion_rate=conversion_rate,
        error=error,
    )
    result = deliver_webhook_event(
        url=subscription.url,
        secret=subscription.secret,
        payload=payload,
    )
    record_webhook_delivery(
        self.db,
        subscription=subscription,
        simulation_id=simulation_id,
        event_type=payload["event"],
        attempt_status=status,
        conversion_rate=conversion_rate,
        error=error,
        result=result,
        payload=payload,
    )

    if not result["ok"]:
        try:
            raise self.retry(exc=RuntimeError(result.get("error", "webhook delivery failed")))
        except Exception:
            pass
    return result


@celery_app.task(name="simulation.health_check")
def health_check() -> dict:
    return {"status": "ok", "worker": "reachable", "ts": _utcnow().isoformat()}
