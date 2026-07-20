from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.api.v1.common import get_owned_project
from app.core.tier_enforcement import enforce_simulation_limit
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.simulation import (
    SimulationCreate,
    SimulationOut,
    SimulationResultOut,
    SimulationStatusOut,
)
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.scored_assumption import (
    ClaimConfidence,
    score_assumptions,
    signal_quality_tier,
)
from app.simulation.scenario_stress import ScenarioStressAnalyzer
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
)
def create_simulation(
    payload: SimulationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.user_id == current_user.id)
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
