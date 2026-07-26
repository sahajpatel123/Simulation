from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.api.v1.common import get_owned_project
from app.core.rate_limiter import rate_limit
from app.core.tier_enforcement import enforce_simulation_limit
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.models.cluster_run_summary import ClusterRunSummary
from app.schemas.cluster_opportunity import ClusterOpportunityMatrixOut
from app.schemas.funnel_diagnosis import FunnelDiagnosisOut
from app.schemas.simulation import (
    SimulationBatchStatusOut,
    SimulationCreate,
    SimulationOut,
    SimulationResultOut,
    SimulationStatusOut,
)
from app.schemas.simulation_comparison import (
    SimulationCompareRequest,
    SimulationComparisonOut,
)
from app.schemas.agent_routing import (
    AgentRoutingDecisionOut,
    AgentRoutingRegistryOut,
    AgentTierEnum,
    TIER_RELATIVE_COST,
    TierCounts,
)
from app.schemas.cohort_retention import CohortRetentionOut
from app.schemas.sensitivity import SensitivityOut
from app.schemas.what_if import WhatIfOut, WhatIfRequest
from app.simulation.agent_hierarchy import AgentHierarchyRouter
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.cluster_opportunity import build_cluster_opportunity_matrix
from app.simulation.comparison import build_simulation_comparison
from app.simulation.cohort_retention import build_cohort_retention
from app.simulation.funnel_diagnosis import build_funnel_diagnosis
from app.simulation.scored_assumption import (
    ClaimConfidence,
    score_assumptions,
    signal_quality_tier,
)
from app.simulation.scenario_stress import ScenarioStressAnalyzer
from app.simulation.sensitivity_analysis import build_sensitivity_analysis
from app.simulation.sim_batch import (
    parse_id_list,
    parse_since,
    summarise_statuses,
)
from app.simulation.what_if import build_what_if_scenario
from app.tasks.simulation_tasks import run_full_simulation
from app.worker import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

_registry = ClusterRegistry()
_clusters_map = {c.cluster_id: c for c in _registry.all_clusters()}


def _signal_suggestions(sq: float, dist: dict) -> list[str]:
    tips: list[str] = []
    if sq < 0.50:
        tips.append(
            "Add externally validated claims (real user testing) to raise signal quality"
        )
    if sq < 0.35:
        tips.append("Replace aspirational language with specific metrics and evidence")
    if (dist.get("ASPIRATIONAL") or 0) > 2:
        tips.append("Reduce aspirational claims — each lowers simulation accuracy")
    if not tips:
        tips.append("Signal quality is good — simulation results are reliable")
    return tips


@router.post(
    "",
    response_model=SimulationStatusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enqueue a full multi-cluster simulation for a project",
    # Rate limit at the IP+path level: protects the DB against a single
    # actor (or compromised script) spamming POSTs at the enqueue path.
    # The per-user monthly quota (2 / 20 / 999 by tier) is enforced
    # inside the handler via enforce_simulation_limit; this outer limit
    # stops the path from being used to probe the DB or generate
    # unhandled errors at high volume.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def create_simulation(
    payload: SimulationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.user_id == current_user.id)
        # Lock the project row so the subsequent "no running sim for this
        # project" check + insert is serialised. Without this, two
        # concurrent POSTs could both observe an empty QUEUED/RUNNING
        # set, both pass the check, and both insert — consuming two
        # tier-quota slots for what the user intended as one click.
        # The lock is released when the surrounding transaction commits.
        .with_for_update()
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    environment = (
        db.query(Environment)
        .filter(Environment.project_id == payload.project_id)
        .first()
    )
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /api/v1/projects/{id}/environments first.",
        )

    if not project.brief_completed_at:
        raise HTTPException(
            status_code=400,
            detail="The Brief must be completed before running a simulation. "
            "Fill in positioning, features, and hook at /briefs first.",
        )

    # Enforce tier quota at enqueue time so over-limit users see a 429
    # immediately rather than receiving a 201 + FAILED row after the
    # Celery task retries twice.
    try:
        enforce_simulation_limit(current_user, db)
    except HTTPException:
        raise
    except Exception:
        # If the quota check itself errors, fall back to the Celery task's
        # own enforcement rather than blocking the request.
        logger.exception(
            "[API] Tier quota pre-check failed for user_id=%s; deferring to worker",
            current_user.id,
        )

    running = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == payload.project_id,
            Simulation.status.in_(["QUEUED", "RUNNING"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation {running.id} is already {running.status} for this project.",
        )

    sim = Simulation(
        project_id=payload.project_id,
        environment_id=environment.id,
        status="QUEUED",
        consumer_volume=payload.consumer_volume,
    )
    db.add(sim)
    db.commit()
    db.refresh(sim)

    task = run_full_simulation.delay(sim.id)
    sim.task_id = task.id
    db.commit()
    db.refresh(sim)

    logger.info(f"[API] Simulation enqueued - simulation_id={sim.id} task_id={task.id}")

    return SimulationStatusOut.model_validate(sim)


@router.get(
    "/worker/health",
    summary="Probe Celery worker with a test task",
    responses=_JSON_200,
)
def worker_health():
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_workers = inspect.ping() or {}
        return {"worker_reachable": bool(active_workers), "workers_online": len(active_workers)}
    except Exception:
        return {"worker_reachable": False, "workers_online": 0}


@router.get(
    "/clusters",
    summary="List 52 customer clusters and registry metadata",
    responses=_JSON_200,
)
def get_cluster_registry():
    clusters = ClusterRegistry().all_clusters()
    return {
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "name": c.name,
                "description": c.description,
                "population_weight": round(c.population_weight, 4),
                "product_affinities": c.product_affinities,
                "demographic_profile": c.demographic_profile,
                "dominant_behavior": c.dominant_behavior_pattern,
            }
            for c in sorted(clusters, key=lambda x: -x.population_weight)
        ],
        "total": len(clusters),
    }


@router.get(
    "/{simulation_id}/signal-quality",
    summary="Signal quality tier and improvement suggestions for a run",
    responses=_JSON_200,
)
def get_signal_quality(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    sq = float(sim.signal_quality or 0.0)
    tier = signal_quality_tier(sq)
    dist = sim.claim_confidence_distribution or {}

    # Re-score project assumptions to surface detailed counts for the UI
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id)
        .all()
    )
    assumption_dicts = [
        {"id": a.id, "text": a.text, "category": a.category, "impact_score": a.impact_score}
        for a in assumptions
    ]
    validated_count = 0
    hard_contradictions = 0
    if assumption_dicts:
        scored, hard_contradictions, _, _ = score_assumptions(assumption_dicts)
        validated_count = sum(
            1
            for s in scored
            if s.claim_confidence
            in (ClaimConfidence.VALIDATED_EXTERNAL, ClaimConfidence.VALIDATED_INTERNAL)
        )

    return {
        "signal_quality": round(sq, 4),
        "tier": tier,
        "validated_assumption_count": validated_count,
        "total_assumption_count": len(assumptions),
        "hard_contradiction_count": hard_contradictions,
        "claim_confidence_distribution": dist,
        "improvement_suggestions": _signal_suggestions(sq, dist),
    }


@router.post(
    "/compare",
    response_model=SimulationComparisonOut,
    summary="Compare 2–5 simulations side-by-side (A/B winner, cluster & domain deltas)",
    responses=_JSON_200,
    # Pure analytics — no LLM, no Celery — but the comparison itself
    # does per-cluster / per-domain rollups over the stored
    # ``results_json``. Cap the path at 30/min/IP so a single actor
    # can't pin a worker on heavy analytics workloads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def compare_simulations(
    payload: SimulationCompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationComparisonOut:
    """
    Side-by-side comparison of 2–5 owned simulations from the **same** project.

    Returns conversion winner / spread / verdict, per-cluster conversion table,
    and cross-simulation domain-finding consensus. Pure analytics — no Celery
    dispatch and no LLM calls.
    """
    sims = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(payload.simulation_ids),
            Project.user_id == current_user.id,
        )
        .all()
    )
    by_id = {s.id: s for s in sims}

    missing = [sid for sid in payload.simulation_ids if sid not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Simulation(s) not found or not owned: {missing}",
        )

    project_ids = {s.project_id for s in sims}
    if len(project_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="All simulations must belong to the same project.",
        )

    incomplete = [
        s.id for s in sims if s.status != "COMPLETED" or not s.results_json
    ]
    if incomplete:
        raise HTTPException(
            status_code=409,
            detail=(
                "All simulations must be COMPLETED with results. "
                f"Not ready: {incomplete}"
            ),
        )

    # Preserve caller order so winner labels A/B/C map to request order.
    ordered = [by_id[sid] for sid in payload.simulation_ids]
    rows = [
        {
            "id": s.id,
            "project_id": s.project_id,
            "status": s.status,
            "results_json": s.results_json,
            "signal_quality": s.signal_quality,
            "created_at": s.created_at,
        }
        for s in ordered
    ]
    registry = {
        cid: {
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cid, cluster in _clusters_map.items()
    }
    return build_simulation_comparison(rows, cluster_registry=registry)


@router.get(
    "/{simulation_id}/status",
    response_model=SimulationStatusOut,
    summary="Simulation row status and errors",
)
def get_simulation_status(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    return SimulationStatusOut.model_validate(sim)


@router.get(
    "/batch",
    response_model=SimulationBatchStatusOut,
    summary="Status of N simulations in one request — for dashboards / progress widgets",
    # DB read of N rows — cap path-spam at 30/min/IP, same as the
    # per-simulation status route.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_simulation_batch_status(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Repeat the param "
            "(``?ids=1&ids=2``) or pass comma-separated values "
            "(``?ids=1,2,3``). Capped at 100 ids per request."
        ),
    ),
    since: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp. Only simulations with "
            "``updated_at >= since`` are returned. Use for "
            "incremental polling — pass back the max "
            "``updated_at`` you saw last time."
        ),
    ),
    sort: str | None = Query(
        default=None,
        max_length=16,
        description=(
            "Sort column. Allowed: id, updated_at. Default: id."
        ),
    ),
    order: str | None = Query(
        default=None,
        max_length=4,
        description="Sort direction: asc or desc. Default: asc.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationBatchStatusOut:
    """Return status for every owned simulation in ``ids``.

    Missing ids (not found OR owned by a different user) are
    reported in ``not_found`` rather than failing the whole batch —
    a UI dashboard polling N simulations shouldn't 404 just because
    one of them was deleted server-side.

    The response carries a ``status_counts`` summary so the UI can
    render aggregate badges without re-iterating ``items``,
    and ``filtered_by_since`` so the dashboard can pin its cursor
    for the next incremental poll.
    """
    try:
        canonical_ids = parse_id_list(ids)
        since_dt = parse_since(since)
        from app.simulation.sim_batch import (
            _normalise_order as _nb_order,
            _normalise_sort as _nb_sort,
        )
        sort_key = _nb_sort(sort)
        order_key = _nb_order(order)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        # Empty input — return an empty result rather than 400, so
        # the UI can probe with an empty list during initial render.
        return SimulationBatchStatusOut(
            items=[],
            not_found=[],
            requested=0,
            status_counts={},
            filtered_by_since=since_dt,
        )

    # Single JOIN that filters out simulations the user doesn't own.
    # We use ``IN`` with the canonical id list and rely on the
    # ``Project.user_id`` join to scope to the caller.
    q = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
    )
    if since_dt is not None:
        q = q.filter(Simulation.updated_at >= since_dt)

    # Sort: id ASC is the default so the response order is stable
    # for incremental polling — pass ``updated_at desc`` when the
    # UI wants "recently changed first".
    sort_attr = getattr(Simulation, sort_key)
    if order_key == "asc":
        primary = sort_attr.asc()
    else:
        primary = sort_attr.desc()
    # Tiebreaker keeps pagination deterministic when sort_key ties.
    if sort_key == "id":
        q = q.order_by(primary)
    else:
        tiebreak = (
            Simulation.id.asc() if order_key == "asc" else Simulation.id.desc()
        )
        q = q.order_by(primary, tiebreak)

    rows = q.all()
    found_ids = {r.id for r in rows}
    not_found = [sid for sid in canonical_ids if sid not in found_ids]

    status_counts = summarise_statuses([r.status for r in rows])

    return SimulationBatchStatusOut(
        items=[SimulationStatusOut.model_validate(r) for r in rows],
        not_found=not_found,
        requested=len(canonical_ids),
        status_counts=status_counts,
        filtered_by_since=since_dt,
    )


@router.get(
    "/{simulation_id}/results",
    response_model=SimulationResultOut,
    summary="Completed simulation results with cluster breakdown",
)
def get_simulation_results(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} - results not available yet.",
        )

    results_json = sim.results_json or {}
    cluster_breakdown_raw = results_json.get("cluster_breakdown", {})
    cluster_breakdown_list = [
        {
            "cluster_id": cid,
            "cluster_name": _clusters_map[cid].name if cid in _clusters_map else cid,
            "conversion_rate": round(float(cr), 4),
            "population_fraction": round(_clusters_map[cid].population_weight, 4)
            if cid in _clusters_map
            else 0.0,
            "agent_count": int(_clusters_map[cid].population_weight * 10000)
            if cid in _clusters_map
            else 0,
            "segment_description": _clusters_map[cid].dominant_behavior_pattern
            if cid in _clusters_map
            else "",
        }
        for cid, cr in sorted(cluster_breakdown_raw.items(), key=lambda x: -x[1])
    ]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    blindspots_to_surface = db.execute(
        text("""
            SELECT blindspot_type, blindspot_value, occurrence_count
            FROM user_market_blindspots
            WHERE user_id=:uid AND occurrence_count >= 2
              AND (last_surfaced_to_user IS NULL OR last_surfaced_to_user < :cutoff)
            ORDER BY occurrence_count DESC LIMIT 3
        """),
        {"uid": current_user.id, "cutoff": cutoff},
    ).fetchall()

    user_blindspots: list[dict] = []
    if blindspots_to_surface:
        db.execute(
            text("""
                UPDATE user_market_blindspots SET last_surfaced_to_user=NOW()
                WHERE user_id=:uid AND occurrence_count >= 2
            """),
            {"uid": current_user.id},
        )
        db.commit()
        user_blindspots = [
            {"type": r.blindspot_type, "value": r.blindspot_value, "count": r.occurrence_count}
            for r in blindspots_to_surface
        ]

    return SimulationResultOut(
        id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        consumer_volume=sim.consumer_volume,
        results=sim.results_json,
        error_message=sim.error_message,
        created_at=sim.created_at,
        updated_at=sim.updated_at,
        cluster_breakdown=cluster_breakdown_list,
        domain_findings=results_json.get("domain_findings", []),
        primary_failure_domain=results_json.get("primary_failure_domain", "unknown"),
        highest_value_cluster=results_json.get("highest_value_cluster", {}),
        architect_accountability=results_json.get("architect_accountability", {}),
        product_type_detected=results_json.get("product_type_detected", ""),
        cluster_narrative=results_json.get("cluster_narrative", ""),
        signal_quality=float(sim.signal_quality or 0.0),
        user_blindspots=user_blindspots,
    )


@router.get(
    "/{simulation_id}/progress",
    summary="Coarse percent progress while a simulation is running",
    responses=_JSON_200,
)
def get_simulation_progress(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    agents_processed = 0
    if sim.results_json and sim.status == "COMPLETED":
        agents_processed = sim.results_json.get("total_agents", 0)

    elapsed = 0.0
    if sim.updated_at and sim.created_at:
        elapsed = (sim.updated_at - sim.created_at).total_seconds()

    pct_map = {"QUEUED": 0, "RUNNING": 50, "COMPLETED": 100, "FAILED": 0}
    pct = pct_map.get(sim.status, 0)

    if sim.status == "RUNNING" and sim.task_id:
        try:
            from app.worker import celery_app

            task_result = celery_app.AsyncResult(sim.task_id)
            if task_result.state == "PROGRESS":
                meta = task_result.info or {}
                pct = meta.get("pct", 50)
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )

    return {
        "simulation_id": sim.id,
        "status": sim.status,
        "pct": pct,
        "agents_processed": agents_processed,
        "agents_total": sim.consumer_volume,
        "elapsed_seconds": round(elapsed, 1),
        "task_id": sim.task_id,
        "error": sim.error_message,
        "results": sim.results_json if sim.status == "COMPLETED" else None,
    }


@router.get(
    "/ws/info",
    summary="WebSocket connection metadata for live progress",
    responses=_JSON_200,
)
def websocket_info():
    from app.core.websocket import ws_manager

    return {
        "active_connections": ws_manager.connection_count,
        "protocol": "ws",
        "endpoint": "/api/v1/ws/simulation/{simulation_id} — auth: first JSON frame {\"type\":\"auth\",\"access_token\":\"<jwt>\"}",
    }


@router.get(
    "/{simulation_id}/stress-scenarios",
    summary="Evaluate simulation resilience across macroeconomic and market stress scenarios",
    responses=_JSON_200,
)
def get_simulation_stress_scenarios(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    if sim.status != "COMPLETED" or not sim.results_json:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} - stress scenario analysis requires completed results.",
        )

    results = sim.results_json or {}
    base_rate = float(results.get("overall_conversion_rate", 0.0))
    cluster_breakdown = results.get("cluster_breakdown", {})
    domain_findings = results.get("domain_findings", [])
    product_type = results.get("product_type_detected", "saas")

    registry_clusters = [
        {
            "cluster_id": c.cluster_id,
            "name": c.name,
            "population_weight": c.population_weight,
        }
        for c in ClusterRegistry().all_clusters()
    ]

    analyzer = ScenarioStressAnalyzer()
    stress_result = analyzer.analyze(
        simulation_id=sim.id,
        base_conversion_rate=base_rate,
        cluster_breakdown=cluster_breakdown,
        cluster_registry=registry_clusters,
        domain_findings=domain_findings,
        product_type=product_type,
    )

    return analyzer.to_dict(stress_result)


@router.post(
    "/{simulation_id}/what-if",
    response_model=WhatIfOut,
    summary="Project conversion impact of new or modified assumptions",
    responses=_JSON_200,
    # Heavy Markov recomputation over the existing results + user
    # assumptions. Cap path-spam at 30/min/IP for the same reason as
    # the simulations POST limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def post_what_if(
    payload: WhatIfRequest,
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatIfOut:
    """
    What-if scenario simulator.

    Takes a completed simulation, applies user-supplied assumptions on top of
    the project's existing assumptions, and re-computes the Markov transition
    matrix to project a new conversion rate.

    Returns the base vs projected conversion rate, per-stage transition
    impacts, revenue projections, and ranked recommendations.

    Pure post-hoc analysis — no Celery dispatch, no LLM calls.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} — what-if analysis requires completed results.",
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    # Fetch environment params
    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    env_params: dict = {}
    if environment:
        env_params = {
            "average_order_value": float(environment.average_order_value or 999.0),
            "price_sensitivity": float(environment.price_sensitivity or 0.5),
            "market_maturity": float(environment.market_maturity or 0.3),
            "consumer_volume": int(environment.consumer_volume or 10000),
            "growth_rate_per_month": float(environment.growth_rate_per_month or 5.0),
        }
        if environment.mode == "SCENARIO" and environment.scenario_type:
            env_params["scenario_type"] = environment.scenario_type
        if environment.manual_params_json:
            env_params.update(environment.manual_params_json)

    # Fetch existing assumptions for the project
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )

    # Build the what-if scenario
    return build_what_if_scenario(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
        new_assumptions=[a.model_dump() for a in payload.assumptions],
        override_price_sensitivity=payload.override_price_sensitivity,
        override_market_maturity=payload.override_market_maturity,
    )


@router.get(
    "/{simulation_id}/cohort-retention",
    response_model=CohortRetentionOut,
    summary="Project per-cluster retention curves, churn rates, and LTV estimates",
    responses=_JSON_200,
)
def get_cohort_retention(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    cluster_limit: int = 52,
) -> CohortRetentionOut:
    """
    Cohort retention projection from a completed simulation's results.

    Uses the cluster conversion rate as a retention proxy, adjusted by
    RetentionArchitect findings when available. Projects survival curves at
    day 1, 7, 30, 90, 180, 365 with churn-risk segmentation and LTV estimates.

    Pure post-hoc analysis — no Celery dispatch, no LLM calls.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} — cohort retention projection requires completed results.",
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    # Fetch cluster_run_summaries for agent counts and drop triggers
    summary_rows = (
        db.query(ClusterRunSummary)
        .filter(ClusterRunSummary.simulation_id == sim.id)
        .all()
    )
    summaries = [
        {
            "cluster_id": row.cluster_id,
            "agents_assigned": row.agents_assigned,
            "agents_converted": row.agents_converted,
            "conversion_rate": row.conversion_rate,
            "primary_drop_trigger": row.primary_drop_trigger,
            "mean_drop_state": row.mean_drop_state,
        }
        for row in summary_rows
    ]

    # Build cluster registry for names/weights
    registry = {
        cid: {
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cid, cluster in _clusters_map.items()
    }

    # Get AOV from environment
    aov = 999.0
    if sim.environment_id:
        env = (
            db.query(Environment)
            .filter(Environment.id == sim.environment_id)
            .first()
        )
        if env:
            aov = float(env.average_order_value or 999.0)

    limit = max(1, min(cluster_limit, 52))

    return build_cohort_retention(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality) if sim.signal_quality is not None else None,
        cluster_summaries=summaries or None,
        cluster_registry=registry,
        aov=aov,
        limit=limit,
    )


@router.get(
    "/{simulation_id}/funnel-diagnosis",
    response_model=FunnelDiagnosisOut,
    summary="Diagnose funnel bottlenecks, cluster drag, and ranked interventions",
    responses=_JSON_200,
)
def get_funnel_diagnosis(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    cluster_limit: int = 10,
) -> FunnelDiagnosisOut:
    """
    Pure post-hoc diagnosis over a completed simulation's ``results_json``
    plus optional ``cluster_run_summaries`` rows.

    Returns the primary bottleneck stage (vs Markov healthy drop-off
    benchmarks), population-weighted cluster drag ranking, aggregated
    drop-trigger histogram, recoverable-conversion estimate, and ranked
    interventions with estimated lift. No Celery dispatch, no LLM calls.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation is {sim.status} — funnel diagnosis requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    limit = cluster_limit if isinstance(cluster_limit, int) else 10
    limit = max(1, min(limit, 52))

    summary_rows = (
        db.query(ClusterRunSummary)
        .filter(ClusterRunSummary.simulation_id == sim.id)
        .all()
    )
    summaries = [
        {
            "cluster_id": row.cluster_id,
            "agents_assigned": row.agents_assigned,
            "agents_converted": row.agents_converted,
            "conversion_rate": row.conversion_rate,
            "primary_drop_trigger": row.primary_drop_trigger,
            "mean_drop_state": row.mean_drop_state,
        }
        for row in summary_rows
    ]

    return build_funnel_diagnosis(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        cluster_summaries=summaries or None,
        cluster_limit=limit,
    )


@router.get(
    "/{simulation_id}/cluster-opportunities",
    response_model=ClusterOpportunityMatrixOut,
    summary="Rank clusters by addressable conversion opportunity for GTM focus",
    responses=_JSON_200,
)
def get_cluster_opportunities(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 52,
    benchmark: float = 0.05,
) -> ClusterOpportunityMatrixOut:
    """
    Build a cluster opportunity matrix from completed results:

      * ``opportunity_score = weight × gap × addressability``
      * Segments: QUICK_WIN / TRANSFORM / NICHE / DEPRIORITIZE
      * Addressable lift estimate + focus recommendations

    Optional ``cluster_run_summaries`` enrich weights and drop triggers.
    Pure analytics — no Celery, no LLM.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation is {sim.status} — cluster opportunities require "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    effective_limit = limit if isinstance(limit, int) else 52
    effective_limit = max(1, min(effective_limit, 52))
    effective_benchmark = (
        float(benchmark) if isinstance(benchmark, (int, float)) else 0.05
    )
    effective_benchmark = max(0.01, min(effective_benchmark, 0.5))

    summary_rows = (
        db.query(ClusterRunSummary)
        .filter(ClusterRunSummary.simulation_id == sim.id)
        .all()
    )
    summaries = [
        {
            "cluster_id": row.cluster_id,
            "agents_assigned": row.agents_assigned,
            "agents_converted": row.agents_converted,
            "conversion_rate": row.conversion_rate,
            "primary_drop_trigger": row.primary_drop_trigger,
            "mean_drop_state": row.mean_drop_state,
        }
        for row in summary_rows
    ]
    registry = {
        cid: {
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cid, cluster in _clusters_map.items()
    }

    return build_cluster_opportunity_matrix(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        cluster_summaries=summaries or None,
        cluster_registry=registry,
        benchmark=effective_benchmark,
        limit=effective_limit,
    )


@router.get(
    "/{simulation_id}/sensitivity",
    response_model=SensitivityOut,
    summary="Analyse which assumptions have the highest sensitivity on conversion",
    responses=_JSON_200,
)
def get_sensitivity_analysis(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SensitivityOut:
    """
    Scenario sensitivity analysis from a completed simulation's results.

    For each project assumption, systematically varies its impact score
    across 5 levels (0%–100%) and measures the resulting conversion rate
    delta. Identifies which assumptions are most critical to validate.

    Pure post-hoc analysis — no Celery dispatch, no LLM calls.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} — sensitivity analysis requires completed results.",
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    # Fetch environment params
    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    env_params: dict = {}
    if environment:
        env_params = {
            "average_order_value": float(environment.average_order_value or 999.0),
            "price_sensitivity": float(environment.price_sensitivity or 0.5),
            "market_maturity": float(environment.market_maturity or 0.3),
            "consumer_volume": int(environment.consumer_volume or 10000),
            "growth_rate_per_month": float(environment.growth_rate_per_month or 5.0),
        }

    # Fetch existing assumptions for the project
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )

    return build_sensitivity_analysis(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
    )


@router.get(
    "/project/{project_id}",
    response_model=list[SimulationStatusOut],
    summary="List all simulations for a project",
)
def list_project_simulations(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sims = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .all()
    )
    return [SimulationStatusOut.model_validate(s) for s in sims]


def _get_owned_simulation(
    simulation_id: int,
    user_id: int,
    db: Session,
) -> Simulation:
    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == user_id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


# ---------------------------------------------------------------------------
# Agent-hierarchy routing — exposes how each cluster is routed to a tier
# (MICRO / WORKER / SUPERVISOR) for UI simulation.
# Pure routing, no DB writes; cached cluster registry loaded once at import.
# ---------------------------------------------------------------------------

_agent_router = AgentHierarchyRouter()


@router.get(
    "/agent-routing/cluster/{cluster_id}",
    response_model=AgentRoutingDecisionOut,
    summary="Routing decision for a single consumer cluster",
    responses=_JSON_200,
    # Read-only, deterministic, but cheap to spam — cap at 60/min/IP so a
    # single actor can't probe the cluster registry at high volume.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_agent_routing_for_cluster(
    cluster_id: str,
    current_user: User = Depends(get_current_user),
) -> AgentRoutingDecisionOut:
    """
    Returns the ``AgentHierarchyRouter`` decision for ``cluster_id``.

    The router maps each of the 52 consumer clusters to a tier:
      * MICRO — fast stochastic outcome (no browser session)
      * WORKER — full Playwright browser session
      * SUPERVISOR — multi-step deliberation for complex decisions

    Exposing the decision helps users reason about simulation cost and
    accuracy without needing to read the routing rules directly.
    ``relative_cost`` is a qualitative multiplier (MICRO=0.05, WORKER=1.0,
    SUPERVISOR=3.5) used to estimate per-agent runtime / token spend.
    """
    if not cluster_id or len(cluster_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid cluster_id")
    if cluster_id not in _clusters_map:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown cluster_id '{cluster_id}'. Use GET /simulations/agent-routing/registry to list valid ids.",
        )
    decision = _agent_router.route(cluster_id)
    return AgentRoutingDecisionOut(
        cluster_id=decision.cluster_id,
        tier=AgentTierEnum(decision.tier.value),
        reason=decision.reason,
        confidence=decision.confidence,
        needs_browser=_agent_router.needs_browser(decision),
        relative_cost=TIER_RELATIVE_COST[decision.tier.value],
    )


@router.get(
    "/agent-routing/registry",
    response_model=AgentRoutingRegistryOut,
    summary="Tier breakdown across all 52 consumer clusters",
    responses=_JSON_200,
    # Same cap as the per-cluster route — both share the path prefix.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_agent_routing_registry(
    current_user: User = Depends(get_current_user),
) -> AgentRoutingRegistryOut:
    """
    Walks every cluster in the live registry and reports:
      * ``tier_counts``    — counts per tier (MICRO / WORKER / SUPERVISOR)
      * ``cost_summary``   — per-tier counts plus ``total_equivalent_cost``
                             (sum of count × relative_cost per tier)
      * ``clusters``       — per-cluster routing decisions
    """
    decisions = _agent_router.route_batch([c.cluster_id for c in _clusters_map.values()])
    summary = _agent_router.tier_summary(decisions)
    tier_counts = TierCounts(
        MICRO=summary["MICRO"],
        WORKER=summary["WORKER"],
        SUPERVISOR=summary["SUPERVISOR"],
        total=summary["total"],
    )
    clusters_out = [
        AgentRoutingDecisionOut(
            cluster_id=d.cluster_id,
            tier=AgentTierEnum(d.tier.value),
            reason=d.reason,
            confidence=d.confidence,
            needs_browser=_agent_router.needs_browser(d),
            relative_cost=TIER_RELATIVE_COST[d.tier.value],
        )
        for d in decisions
    ]
    # Stable ordering: tier priority, then cluster id.
    tier_rank = {"SUPERVISOR": 0, "MICRO": 1, "WORKER": 2}
    clusters_out.sort(key=lambda c: (tier_rank.get(c.tier.value, 99), c.cluster_id))

    cost_summary: dict[str, float | int] = {
        "MICRO": tier_counts.MICRO,
        "WORKER": tier_counts.WORKER,
        "SUPERVISOR": tier_counts.SUPERVISOR,
        "total_equivalent_cost": round(
            tier_counts.MICRO * TIER_RELATIVE_COST["MICRO"]
            + tier_counts.WORKER * TIER_RELATIVE_COST["WORKER"]
            + tier_counts.SUPERVISOR * TIER_RELATIVE_COST["SUPERVISOR"],
            2,
        ),
    }

    return AgentRoutingRegistryOut(
        generated_at=datetime.now(timezone.utc).isoformat(),
        tier_counts=tier_counts,
        cost_summary=cost_summary,
        clusters=clusters_out,
    )
