from __future__ import annotations

import json
import logging
import math
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.cache_namespaces import _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE
from app.api.v1.common import get_owned_project
from app.api.v1.projects import (
    _ACTIVITY_FEED_CACHE_NAMESPACE,
    _ADOPTION_MILESTONES_CACHE_NAMESPACE,
    _LATEST_SNAPSHOT_CACHE_NAMESPACE,
    _NEXT_ACTION_CACHE_NAMESPACE,
    _PROJECT_EXPORT_CACHE_NAMESPACE,
    _PROJECT_HEALTH_CACHE_NAMESPACE,
    _STALE_CHECK_CACHE_NAMESPACE,
    _STATUS_BANNER_CACHE_NAMESPACE,
)
from app.api.v1.users import (
    _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
    _USER_DASHBOARD_CACHE_NAMESPACE,
    _USER_DECISION_RATE_CACHE_NAMESPACE,
    _USER_DECISION_VELOCITY_CACHE_NAMESPACE,
    _USER_INSIGHTS_CACHE_NAMESPACE,
    _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
    _USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
    _USER_NOTIFICATIONS_CACHE_NAMESPACE,
    _USER_OLDEST_OPEN_ITEM_CACHE_NAMESPACE,
    _USER_OUTCOME_RATE_CACHE_NAMESPACE,
    _USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
    _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
    _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
    _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
    _USER_QUICK_STATS_CACHE_NAMESPACE,
    _USER_RUNS_PER_WEEK_CACHE_NAMESPACE,
    _USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
    _USER_SIM_FAILURE_RATE_CACHE_NAMESPACE,
    _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
    _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
)
from app.core.deps import get_current_user, get_db
from app.core.progress_bridge import progress_bridge
from app.core.rate_limiter import rate_limit
from app.core.redis_client import get_redis_client
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
from app.core.tier_enforcement import enforce_simulation_limit
from app.models.assumption import Assumption
from app.models.cluster_run_summary import ClusterRunSummary
from app.models.environment import Environment
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.activation_funnel import ActivationFunnelOut
from app.schemas.after_sales import AfterSalesOut
from app.schemas.agent_routing import (
    TIER_RELATIVE_COST,
    AgentRoutingDecisionOut,
    AgentRoutingRegistryOut,
    AgentTierEnum,
    TierCounts,
)
from app.schemas.assumption_cascade import AssumptionCascadeOut
from app.schemas.assumption_postmortem import AssumptionPostmortemOut
from app.schemas.channel_attribution import ChannelAttributionOut
from app.schemas.cluster_opportunity import ClusterOpportunityMatrixOut
from app.schemas.cohort_retention import CohortRetentionOut
from app.schemas.competitive_moat import CompetitiveMoatOut
from app.schemas.cultural_fit import CulturalFitOut
from app.schemas.distribution_channels import DistributionChannelsOut
from app.schemas.ecosystem_compatibility import EcosystemCompatibilityOut
from app.schemas.feature_prioritization import FeaturePrioritizationOut
from app.schemas.fix_leverage import FixLeverageOut
from app.schemas.founder_action_plan import FounderActionPlanOut
from app.schemas.founder_brief import FounderBriefOut
from app.schemas.funnel_diagnosis import FunnelDiagnosisOut
from app.schemas.launch_checklist import LaunchChecklistOut
from app.schemas.market_concentration import MarketConcentrationOut
from app.schemas.market_sizing import MarketSizingOut
from app.schemas.market_timing import MarketTimingOut
from app.schemas.prediction_range import PredictionRangeOut
from app.schemas.pricing_optimization import PricingOptimizationOut
from app.schemas.retention_churn import RetentionChurnOut
from app.schemas.sensitivity import SensitivityOut
from app.schemas.setup_friction import SetupFrictionOut
from app.schemas.simulation import (
    ArchitectAccuracyBridgeOut,
    ArchitectBiasTrendOut,
    ArchitectDrillDownOut,
    ArchitectLeaderboardOut,
    CalibrationHealthOut,
    ClusterDiffOut,
    ClusterDrillDownOut,
    ClusterOverlapMatrixOut,
    ClustersAggregateOut,
    ClusterTrendOut,
    DatabaseHealthOut,
    FindingsAggregateOut,
    FindingsTrendOut,
    OutcomesDigestOut,
    OutlierDetectionOut,
    PortfolioNarrativeOut,
    PortfolioSummaryOut,
    PortfolioTrendOut,
    ProjectPortfolioRollupOut,
    RedisHealthOut,
    SimDiffOut,
    SimulationAnomaliesOut,
    SimulationBatchStatusOut,
    SimulationCreate,
    SimulationResultOut,
    SimulationSensitivityMatrixOut,
    SimulationStatusOut,
)
from app.schemas.simulation_comparison import (
    SimulationCompareRequest,
    SimulationComparisonOut,
)
from app.schemas.simulation_quality import SimulationQualityOut
from app.schemas.support_friction import SupportFrictionOut
from app.schemas.sustainability_positioning import SustainabilityPositioningOut
from app.schemas.trust_barriers import TrustBarriersOut
from app.schemas.unit_economics import UnitEconomicsOut
from app.schemas.validation_experiment import ValidationExperimentPlanOut
from app.schemas.validation_roi import ValidationRoiOut
from app.schemas.virality_growth import ViralityGrowthOut
from app.schemas.what_if import WhatIfOut, WhatIfRequest
from app.schemas.what_if_batch import WhatIfBatchOut, WhatIfBatchRequest
from app.simulation.activation_funnel import build_activation_funnel
from app.simulation.after_sales_read import build_after_sales_read
from app.simulation.agent_hierarchy import AgentHierarchyRouter
from app.simulation.anomaly_detector import detect_simulation_anomalies
from app.simulation.architect_bias_trend import (
    build_architect_bias_trend,
)
from app.simulation.architect_bias_trend import (
    normalise_bin as normalise_bias_bin,
)
from app.simulation.architect_drill_down import (
    build_architect_drill_down,
)
from app.simulation.architect_leaderboard import (
    build_architect_leaderboard,
)
from app.simulation.assumption_cascade_read import build_assumption_cascade
from app.simulation.assumption_postmortem import build_assumption_postmortem
from app.simulation.calibration_health import (
    build_calibration_health,
)
from app.simulation.calibration_health_export import calibration_health_to_csv
from app.simulation.channel_attribution_read import build_channel_attribution
from app.simulation.cluster_diff import build_cluster_diff
from app.simulation.cluster_drill_down import (
    build_cluster_drill_down,
)
from app.simulation.cluster_drill_down import (
    normalise_outlier_threshold as normalise_drill_outlier,
)
from app.simulation.cluster_opportunity import build_cluster_opportunity_matrix
from app.simulation.cluster_overlap_export import (
    cluster_overlap_to_csv,
    cluster_overlap_to_json,
)
from app.simulation.cluster_overlap_matrix import (
    MAX_CLUSTERS as _MAX_MATRIX_CLUSTERS,
)
from app.simulation.cluster_overlap_matrix import (
    build_cluster_overlap_matrix,
)
from app.simulation.cluster_trend import (
    build_cluster_trend,
)
from app.simulation.cluster_trend import (
    normalise_bin as normalise_trend_bin,
)
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.competitive_moat import build_competitive_moat
from app.simulation.conductor import Conductor
from app.simulation.cultural_fit import build_cultural_fit
from app.simulation.distribution_channels import build_distribution_channels
from app.simulation.ecosystem_compatibility import build_ecosystem_compatibility
from app.simulation.feature_prioritization import build_feature_prioritization
from app.simulation.feature_prioritization_export import (
    feature_prioritization_to_csv,
    feature_prioritization_to_json,
    feature_prioritization_to_markdown,
)
from app.simulation.findings_export import (
    extract_findings,
    findings_to_csv,
    findings_to_markdown,
)
from app.simulation.findings_trend import (
    build_findings_trend,
)
from app.simulation.findings_trend import (
    normalise_bin as normalise_findings_bin,
)
from app.simulation.findings_trend import (
    normalise_severity as normalise_findings_severity,
)
from app.simulation.fix_leverage import build_fix_leverage
from app.simulation.founder_action_plan_export import (
    founder_action_plan_to_csv,
    founder_action_plan_to_json,
)
from app.simulation.founder_brief import build_founder_brief
from app.simulation.launch_checklist import build_launch_checklist
from app.simulation.launch_checklist_export import (
    launch_checklist_to_csv,
    launch_checklist_to_json,
    launch_checklist_to_markdown,
)
from app.simulation.market_concentration import build_market_concentration
from app.simulation.market_sizing import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_MARKET_SIZE,
    DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
    DEFAULT_TARGET_MARKET_FRACTION,
    MAX_MARKET_SIZE,
    MAX_TARGET_MARKET_FRACTION,
    MIN_MARKET_SIZE,
    MIN_TARGET_MARKET_FRACTION,
    build_market_sizing,
)
from app.simulation.market_timing_read import build_market_timing
from app.simulation.outlier_detection import (
    build_outlier_detection,
    normalise_z_threshold,
)
from app.simulation.portfolio_narrative import (
    build_portfolio_narrative,
)
from app.simulation.prediction_range import (
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range,
    extract_predicted_conversion,
)
from app.simulation.pricing_optimization import build_pricing_optimization
from app.simulation.product_type import ProductType
from app.simulation.project_rollup import (
    build_project_portfolio_rollup,
)
from app.simulation.retention_churn_read import build_retention_churn
from app.simulation.sensitivity_export import (
    sensitivity_to_csv,
    sensitivity_to_json,
)
from app.simulation.sensitivity_matrix import compute_simulation_sensitivity_matrix
from app.simulation.setup_friction import build_setup_friction
from app.simulation.sim_diff import build_sim_diff
from app.simulation.simulation_export import (
    build_simulation_export,
    simulation_to_csv,
)
from app.simulation.support_friction import build_support_friction
from app.simulation.sustainability_positioning import (
    build_sustainability_positioning,
)
from app.simulation.trust_barriers import build_trust_barriers
from app.simulation.unit_economics import build_unit_economics
from app.simulation.unit_economics_export import unit_economics_to_csv
from app.simulation.validation_experiment_planner import build_validation_experiment_plan
from app.simulation.validation_roi import build_validation_roi
from app.simulation.virality_growth import build_virality_growth
from app.simulation.what_if_batch_export import (
    what_if_batch_to_csv,
    what_if_batch_to_json,
    what_if_batch_to_markdown,
)

# Short TTL — the dashboard polls /portfolio-narrative
# while a batch is open, but a new sim creation must be
# reflected promptly so we don't exceed ~30s of staleness.
_PORTFOLIO_NARRATIVE_CACHE_TTL_S: int = 30
_PORTFOLIO_NARRATIVE_CACHE_NAMESPACE: str = "portfolio-narrative"
from app.simulation.architect_accuracy_bridge import (
    bridge_architect_accuracy,
)
from app.simulation.architect_accuracy_bridge import (
    normalise_severity as normalise_bridge_severity,
)
from app.simulation.architect_accuracy_bridge import (
    normalise_top_n as normalise_bridge_top_n,
)
from app.simulation.clusters_aggregate import (
    aggregate_clusters,
)
from app.simulation.clusters_aggregate import (
    normalise_top_n as normalise_clusters_top_n,
)
from app.simulation.cohort_retention import build_cohort_retention
from app.simulation.comparison import build_simulation_comparison
from app.simulation.conductor import _ARCHITECTS as _architect_registry
from app.simulation.findings_aggregate import (
    aggregate_findings,
    normalise_architect_filter,
    normalise_severity,
    normalise_top_n,
)
from app.simulation.founder_action_plan import build_founder_action_plan
from app.simulation.funnel_diagnosis import build_funnel_diagnosis
from app.simulation.funnel_diagnosis_export import (
    funnel_diagnosis_to_csv,
    funnel_diagnosis_to_json,
    funnel_diagnosis_to_markdown,
)
from app.simulation.outcomes_digest import (
    aggregate_outcomes,
    normalise_outlier_threshold,
)
from app.simulation.portfolio_summary import (
    build_portfolio_summary,
    portfolio_to_csv,
)
from app.simulation.portfolio_trend import compute_portfolio_trend
from app.simulation.scenario_stress import ScenarioStressAnalyzer
from app.simulation.scored_assumption import (
    ClaimConfidence,
    score_assumptions,
    signal_quality_tier,
)
from app.simulation.sensitivity_analysis import build_sensitivity_analysis
from app.simulation.sim_batch import (
    parse_id_list,
    parse_since,
    summarise_statuses,
)
from app.simulation.simulation_comparison_export import (
    simulation_comparison_to_csv,
    simulation_comparison_to_json,
    simulation_comparison_to_markdown,
)
from app.simulation.simulation_quality import build_simulation_quality
from app.simulation.what_if import build_what_if_scenario
from app.simulation.what_if_batch import build_what_if_batch
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

    # Bust the cached portfolio-narrative + the per-project
    # next-action + the activity feed so the next GETs
    # reflect the new sim rather than waiting out the TTL.
    cache_invalidate(
        namespace=_PORTFOLIO_NARRATIVE_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_DASHBOARD_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_PROJECT_HEALTH_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_NOTIFICATIONS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_PROJECT_EXPORT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_QUICK_STATS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_DECISION_VELOCITY_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_DECISION_RATE_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OUTCOME_RATE_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_SIM_FAILURE_RATE_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_RUNS_PER_WEEK_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OLDEST_OPEN_ITEM_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

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
    "/db-health",
    summary="Probe database connectivity with SELECT 1",
    response_model=DatabaseHealthOut,
    responses={
        200: {"description": "Database is reachable"},
        503: {"description": "Database is unreachable"},
    },
)
def db_health(
    db: Session = Depends(get_db),
) -> DatabaseHealthOut:
    """Health probe for the PostgreSQL connection used by the API."""
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health probe failed")
        raise HTTPException(
            status_code=503,
            detail="Database unreachable",
        ) from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    return DatabaseHealthOut(
        database="reachable",
        latency_ms=round(max(0.0, latency_ms), 3),
        checked_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/redis-health",
    summary="Probe Redis connectivity with PING",
    response_model=RedisHealthOut,
    responses={
        200: {"description": "Redis is reachable or unconfigured"},
        503: {"description": "Redis is unreachable"},
    },
)
def redis_health() -> RedisHealthOut:
    """Health probe for the Redis connection used by the API."""
    client = get_redis_client()
    if client is None:
        return RedisHealthOut(redis="unconfigured")
    started = time.perf_counter()
    try:
        pong = client.ping()
    except Exception as exc:
        logger.exception("Redis health probe failed")
        raise HTTPException(
            status_code=503,
            detail="Redis unreachable",
        ) from exc
    if not pong:
        logger.error("Redis health probe failed: PING returned %r", pong)
        raise HTTPException(
            status_code=503,
            detail="Redis unreachable",
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return RedisHealthOut(
        redis="reachable",
        latency_ms=round(max(0.0, latency_ms), 3),
        checked_at=datetime.now(UTC).isoformat(),
    )


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
    "/compare/export",
    response_class=StreamingResponse,
    summary="Export a 2–5 simulation comparison as CSV, JSON, or Markdown",
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_simulation_comparison(
    simulation_ids: str = Query(
        ...,
        min_length=3,
        max_length=512,
        description=(
            "Comma-separated list of 2–5 simulation IDs from the same "
            "project, in the desired comparison order."
        ),
    ),
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "comparison payload; ``md`` returns a founder-facing "
            "Markdown brief."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export a simulation comparison as CSV, JSON, or Markdown.

    Default ``format=csv`` renders the summary, simulation refs,
    per-cluster conversion + delta table, and domain-finding consensus as
    a multi-section spreadsheet. ``json`` returns the raw comparison
    document for machine consumers, and ``md`` returns a concise
    founder-facing Markdown brief.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; "
                "expected 'csv', 'json', or 'md'"
            ),
        )

    try:
        ids = [int(token) for token in simulation_ids.split(",") if token.strip()]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="simulation_ids must be comma-separated integers",
        ) from exc
    if len(ids) < 2 or len(ids) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="simulation_ids must contain between 2 and 5 simulation IDs",
        )
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="simulation_ids must be unique",
        )
    if any(sid <= 0 for sid in ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="simulation_ids must be positive integers",
        )

    result = compare_simulations(
        payload=SimulationCompareRequest(simulation_ids=ids),
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "project_id": result.project_id,
        "comparison_id": result.comparison_id,
    }

    if fmt == "json":
        body = simulation_comparison_to_json(
            result,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="simulation-comparison.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "md":
        body = simulation_comparison_to_markdown(
            result,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="simulation-comparison.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = simulation_comparison_to_csv(result, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="simulation-comparison.csv"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


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
    ordered = _load_simulations_for_comparison(
        payload.simulation_ids,
        db=db,
        current_user_id=current_user.id,
    )
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


def _load_simulations_for_comparison(
    simulation_ids: list[int],
    *,
    db: Session,
    current_user_id: int,
) -> list[Simulation]:
    """Fetch and validate owned completed simulations for comparison.

    Shared by the JSON comparison endpoint and the export endpoint so both
    paths enforce identical ownership, same-project, and completion rules.
    """
    sims = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(simulation_ids),
            Project.user_id == current_user_id,
        )
        .all()
    )
    by_id = {s.id: s for s in sims}

    missing = [sid for sid in simulation_ids if sid not in by_id]
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
    return [by_id[sid] for sid in simulation_ids]


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
        )
        from app.simulation.sim_batch import (
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
    "/aggregate/findings",
    response_model=FindingsAggregateOut,
    summary="Aggregate domain findings across N simulations (portfolio view)",
    # DB read of N result_json blobs — cap path-spam at 30/min/IP.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def aggregate_simulation_findings(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch`` — repeat the param or "
            "pass comma-separated values. Capped at 100 ids."
        ),
    ),
    min_severity: str | None = Query(
        default=None,
        max_length=16,
        description=(
            "Filter finding list to >= this severity. Allowed: "
            "INFO, WARNING, CRITICAL. Default: INFO."
        ),
    ),
    top_n: int | None = Query(
        default=None,
        ge=1,
        description=(
            "How many top architects / top findings to surface "
            "(cap 100). Default: 5."
        ),
    ),
    architect: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "Optional case-insensitive architect name to "
            "narrow the rollup. Global severity_breakdown still "
            "reflects all findings; only by_architect / by_cluster "
            "/ top_findings are filtered."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FindingsAggregateOut:
    """Cross-simulation findings rollup.

    Powers the "portfolio view" dashboard: "across my 12 simulations,
    which architect keeps flagging critical issues?" The
    ``shared_domain_count`` field highlights the systemic failures
    that appear in >= half of the supplied sims. The ``by_cluster``
    and ``top_findings`` fields surface the *which user segment* and
    *show me the worst thing* views respectively.
    """
    try:
        canonical_ids = parse_id_list(ids)
        min_sev = normalise_severity(min_severity)
        arch_filter = normalise_architect_filter(architect)
        effective_top_n = normalise_top_n(top_n)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return FindingsAggregateOut(architect_filter=architect)

    # Single JOIN: scope to the current user + grab the persisted
    # results_json blobs. We only fetch completed sims — aggregating
    # findings from a FAILED/RUNNING sim would always return empty
    # and just inflate the sims_with_findings denominator.
    rows = (
        db.query(Simulation.id, Simulation.results_json)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Simulation.status == "COMPLETED",
            Project.user_id == current_user.id,
        )
        .all()
    )
    # Preserve the user's requested order (parse_id_list dedupes
    # preserving first-seen) so the UI can render "the order I
    # asked for" even though the SQL order is undetermined.
    by_id = {r.id: r.results_json for r in rows}
    ordered_results = [by_id[sid] for sid in canonical_ids if sid in by_id]

    aggregate = aggregate_findings(
        ordered_results,
        min_severity=min_sev,
        top_n=effective_top_n,
        architect=arch_filter,
    )
    return FindingsAggregateOut(**aggregate)


@router.get(
    "/aggregate/outcomes",
    response_model=OutcomesDigestOut,
    summary="Aggregate predicted-vs-actual outcomes across N simulations",
    # DB read of N outcome rows — same cap as the findings aggregate.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def aggregate_simulation_outcomes(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch`` — repeat the param or pass "
            "comma-separated values. Capped at 100 ids."
        ),
    ),
    outlier_threshold: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Absolute variance (predicted − actual) above which "
            "a pair is counted as an outlier. Default 0.10 (10pp). "
            "Clamped to [0.0, 1.0] so a UI typo can't widen the "
            "outlier definition."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomesDigestOut:
    """Cross-simulation calibration-at-scale rollup.

    For each supplied simulation id, we find the latest Outcome
    record the founder has submitted against it and treat that
    row's ``predicted_conversion_rate`` and
    ``actual_conversion_rate`` as one ``(predicted, actual)``
    pair. The aggregate reports MAE / MAPE / RMSE plus a
    direction breakdown (over / under / exact) so the dashboard
    can render "across my 12 sims, we over-predicted conversion
    6×, under-predicted 2×".

    Pairs with a missing predicted *or* actual value are still
    counted in ``simulation_count`` (so the UI can show "X of Y
    actionable") but excluded from MAE / MAPE / RMSE.
    """
    try:
        canonical_ids = parse_id_list(ids)
        threshold = normalise_outlier_threshold(outlier_threshold)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return OutcomesDigestOut()

    # Scope the Outcome rows to the current user via Simulation →
    # Project ownership. Pull every outcome for the requested sims
    # (newest-first) and dedupe to the latest per sim in Python —
    # the row count is bounded by MAX_BATCH_SIZE * small constant.
    rows = (
        db.query(
            Outcome.simulation_id,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .join(Simulation, Outcome.simulation_id == Simulation.id)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Outcome.simulation_id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
        .order_by(Outcome.created_at.desc())
        .all()
    )

    # Build (predicted, actual) pairs in the user's requested order;
    # only the first (newest) outcome per sim id is kept.
    pairs: list[tuple[float | None, float | None]] = []
    seen_sim_ids: set[int] = set()
    for sid in canonical_ids:
        if sid in seen_sim_ids:
            continue
        match = next((r for r in rows if r.simulation_id == sid), None)
        if match is None:
            # No outcome row for this sim — count it as a missing
            # pair so the UI can render "Y of Z have outcomes".
            pairs.append((None, None))
        else:
            pairs.append(
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                )
            )
        seen_sim_ids.add(sid)

    return OutcomesDigestOut(
        **aggregate_outcomes(
            pairs,
            outlier_threshold=threshold,
            sim_ids=canonical_ids,
        )
    )


@router.get(
    "/aggregate/clusters",
    response_model=ClustersAggregateOut,
    summary="Aggregate cluster conversion across N simulations (portfolio view)",
    # DB read of N result_json blobs — same cap as the sibling
    # aggregate endpoints so the path can't be used to probe rows
    # the caller doesn't own.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def aggregate_simulation_clusters(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch`` — repeat the param or "
            "pass comma-separated values. Capped at 100 ids."
        ),
    ),
    top_n: int | None = Query(
        default=None,
        ge=1,
        description=(
            "How many top laggard / top performer cluster ids to "
            "surface (cap 100). Default: 5."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClustersAggregateOut:
    """Cross-simulation cluster portfolio rollup.

    Powers the "which user segment is consistently the
    weakest / strongest?" widget: across the user's selected
    simulations, every cluster that appears in any
    ``cluster_breakdown`` gets a ``mean / min / max / std``
    conversion summary so the dashboard can rank clusters by
    under- or over-performance.
    """
    try:
        canonical_ids = parse_id_list(ids)
        effective_top_n = normalise_clusters_top_n(top_n)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return ClustersAggregateOut()

    # Build a {cluster_id: name} lookup from the registered cluster
    # catalog so the response rows carry human-readable names.
    cluster_names = {
        cluster.cluster_id: cluster.name
        for cluster in _registry.all_clusters()
    }

    rows = (
        db.query(Simulation.id, Simulation.results_json)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Simulation.status == "COMPLETED",
            Project.user_id == current_user.id,
        )
        .all()
    )
    by_id = {r.id: r.results_json for r in rows}
    ordered_results = [
        by_id[sid] for sid in canonical_ids if sid in by_id
    ]

    aggregate = aggregate_clusters(
        ordered_results,
        cluster_names=cluster_names,
        top_n=effective_top_n,
    )
    return ClustersAggregateOut(**aggregate)


@router.get(
    "/aggregate/architect-accuracy",
    response_model=ArchitectAccuracyBridgeOut,
    summary=(
        "Cross-reference findings with outcomes to surface biased architects"
    ),
    # DB read of N (sim, outcome) pairs — same cap as the sibling
    # aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def aggregate_architect_accuracy(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch`` — repeat the param or "
            "pass comma-separated values. Capped at 100 ids."
        ),
    ),
    min_severity: str | None = Query(
        default=None,
        max_length=16,
        description=(
            "Filter finding list to >= this severity. Allowed: "
            "INFO, WARNING, CRITICAL. Default: INFO."
        ),
    ),
    top_n: int | None = Query(
        default=None,
        ge=1,
        description=(
            "How many most-biased architects to surface "
            "(cap 100). Default: 5."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchitectAccuracyBridgeOut:
    """Cross-simulation architect calibration bridge.

    Joins each owned simulation's ``domain_findings`` with its
    latest ``Outcome`` row so we can compute, per architect: on
    the sims where the architect flagged findings, did the model
    actually over- or under-predict conversion? Architects whose
    CRITICAL flags consistently correlate with bias are flagged
    as ``needs_review`` so the dashboard can investigate.
    """
    try:
        canonical_ids = parse_id_list(ids)
        min_sev = normalise_bridge_severity(min_severity)
        effective_top_n = normalise_bridge_top_n(top_n)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return ArchitectAccuracyBridgeOut(min_severity=min_sev)

    # Single JOIN: pull every outcome row for the requested sims
    # (newest-first), scope to the current user via Simulation →
    # Project ownership. We keep only the latest outcome per sim
    # in Python — bounded by MAX_BATCH_SIZE * small constant.
    rows = (
        db.query(
            Simulation.id,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome,
            Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
        .order_by(Outcome.created_at.desc())
        .all()
    )

    # Build ``(results_json, (predicted, actual))`` pairs in the
    # user's requested order; only the first (newest) outcome per
    # sim id is kept. Sims without any outcome get ``(None, None)``.
    pairs: list[
        tuple[dict | None, tuple[float | None, float | None]]
    ] = []
    seen_sim_ids: set[int] = set()
    for sid in canonical_ids:
        if sid in seen_sim_ids:
            continue
        seen_sim_ids.add(sid)
        match = next((r for r in rows if r.id == sid), None)
        if match is None:
            pairs.append((None, (None, None)))
            continue
        pairs.append(
            (
                match.results_json,
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                ),
            )
        )

    bridge = bridge_architect_accuracy(
        pairs,
        min_severity=min_sev,
        top_n=effective_top_n,
    )
    return ArchitectAccuracyBridgeOut(**bridge)


@router.get(
    "/architect-leaderboard",
    response_model=ArchitectLeaderboardOut,
    summary=(
        "Ranked list of architects across the batch by composite "
        "score (|calibration_variance| × finding_count)"
    ),
    # Same cap as the other aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_architect_leaderboard(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids the "
            "leaderboard returns an empty ranking."
        ),
    ),
    top_n: int | None = Query(
        default=None,
        ge=1,
        description=(
            "How many top architects to return. Default cap is "
            "MAX_LEADERS (50). Useful for limiting the "
            "dashboard tile."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchitectLeaderboardOut:
    """Single ranked list of architects to investigate.

    Runs the architect-accuracy bridge on the supplied batch
    (or the full owned set when ``ids`` is omitted), then
    synthesises the bridge's ``by_architect`` rows into a
    single composite score = ``|calibration_variance| ×
    finding_count``. Architects that flagged more findings AND
    were more biased rank highest.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return ArchitectLeaderboardOut()

    rows = (
        db.query(
            Simulation.id,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
        .order_by(Outcome.created_at.desc())
        .all()
    )

    by_id: dict[int, object] = {}
    for r in rows:
        if r.id in by_id:
            continue
        by_id[r.id] = r
    outcome_pairs: list[
        tuple[list[dict], tuple[float | None, float | None]]
    ] = []
    for sid in canonical_ids:
        match = by_id.get(sid)
        if match is None:
            continue
        outcome_pairs.append(
            (
                (match.results_json or {}).get("domain_findings")
                or [],
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                ),
            )
        )

    bridge = bridge_architect_accuracy(outcome_pairs)
    payload = build_architect_leaderboard(
        bridge.get("by_architect"),
        top_n=top_n,
    )
    return ArchitectLeaderboardOut(**payload)


@router.get(
    "/portfolio-summary",
    response_model=PortfolioSummaryOut,
    summary=(
        "One-call dashboard payload fusing findings, outcomes, "
        "clusters, and architect accuracy"
    ),
    # Composite of the four sibling aggregates → same cap.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_portfolio_summary(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch`` — repeat the param or "
            "pass comma-separated values. Capped at 100 ids."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioSummaryOut:
    """Single-call portfolio view for the dashboard.

    Composes findings, outcomes, clusters, and architect-accuracy
    aggregates in one round-trip so the portfolio-view home screen
    doesn't have to issue four separate requests. The cross-
    aggregate ``correlated_bias_count`` and ``overall_health`` are
    computed here from the fused payloads.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return PortfolioSummaryOut()

    # Single DB round-trip: scope to current user via Simulation →
    # Project ownership and grab (results_json, latest outcome) for
    # each requested sim id. The LEFT JOIN keeps sims without any
    # outcome row in the result set.
    rows = (
        db.query(
            Simulation.id,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
        .order_by(Outcome.created_at.desc())
        .all()
    )

    # Preserve user's requested order; keep latest outcome per sim.
    by_id: dict[int, object] = {}
    for r in rows:
        if r.id in by_id:
            continue
        by_id[r.id] = r
    ordered_results: list[dict] = []
    outcome_pairs: list[
        tuple[dict | None, tuple[float | None, float | None]]
    ] = []
    for sid in canonical_ids:
        match = by_id.get(sid)
        if match is None:
            continue
        ordered_results.append(match.results_json)
        outcome_pairs.append(
            (
                match.results_json,
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                ),
            )
        )

    # Cluster name lookup for the clusters aggregate.
    cluster_names = {
        cluster.cluster_id: cluster.name
        for cluster in _registry.all_clusters()
    }

    # Run the four sub-aggregates. Each helper is pure-Python so
    # the total CPU cost is bounded by the 100-sim batch cap.
    findings_payload = aggregate_findings(
        ordered_results,
        min_severity=normalise_severity(None),
        top_n=normalise_top_n(None),
        architect=None,
    )
    outcomes_payload = aggregate_outcomes(
        [
            # outcomes_digest wants the ``(predicted, actual)`` pair
            # in canonical order — re-project from outcome_pairs.
            (pair[1][0], pair[1][1])
            for pair in outcome_pairs
        ],
        outlier_threshold=normalise_outlier_threshold(None),
        sim_ids=canonical_ids[: len(outcome_pairs)],
    )
    clusters_payload = aggregate_clusters(
        ordered_results,
        cluster_names=cluster_names,
        top_n=normalise_clusters_top_n(None),
    )
    bridge_payload = bridge_architect_accuracy(
        outcome_pairs,
        min_severity=normalise_bridge_severity(None),
        top_n=normalise_bridge_top_n(None),
    )

    summary = build_portfolio_summary(
        simulation_count=len(ordered_results),
        findings_payload=findings_payload,
        outcomes_payload=outcomes_payload,
        clusters_payload=clusters_payload,
        architect_accuracy_payload=bridge_payload,
    )
    return PortfolioSummaryOut(**summary)


@router.get(
    "/portfolio-export.csv",
    summary=(
        "Spreadsheet export of the portfolio summary — same "
        "data as /portfolio-summary, formatted as multi-section "
        "CSV (or JSON when ?format=json)"
    ),
    response_class=StreamingResponse,
    # Composite of the four sibling aggregates → same cap.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_portfolio_export_csv(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/portfolio-summary``. Optional; without ids, the "
            "export contains only the empty-summary placeholder."
        ),
    ),
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly multi-section document; "
            "``json`` returns the raw portfolio summary as "
            "JSON. Anything other than ``json`` falls back to "
            "``csv``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Spreadsheet export of the portfolio summary.

    Default ``format=csv`` returns the multi-section CSV with
    a metadata header at the top (generated_at, user_id,
    simulation_count). ``format=json`` returns the raw summary
    payload so machine-to-machine consumers don't have to
    parse the CSV.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    cluster_names = {
        cluster.cluster_id: cluster.name
        for cluster in _registry.all_clusters()
    }

    if not canonical_ids:
        # Empty batch — same well-formed empty export, with
        # provenance metadata so users see "this is your export"
        # even when no sims were requested.
        summary = build_portfolio_summary(simulation_count=0)
    else:
        rows = (
            db.query(
                Simulation.id,
                Simulation.results_json,
                Outcome.predicted_conversion_rate,
                Outcome.actual_conversion_rate,
                Outcome.created_at,
            )
            .outerjoin(
                Outcome, Outcome.simulation_id == Simulation.id,
            )
            .join(Project, Simulation.project_id == Project.id)
            .filter(
                Simulation.id.in_(canonical_ids),
                Project.user_id == current_user.id,
            )
            .order_by(Outcome.created_at.desc())
            .all()
        )

        by_id: dict[int, object] = {}
        for r in rows:
            if r.id in by_id:
                continue
            by_id[r.id] = r
        ordered_results: list[dict] = []
        outcome_pairs: list[
            tuple[dict | None, tuple[float | None, float | None]]
        ] = []
        for sid in canonical_ids:
            match = by_id.get(sid)
            if match is None:
                continue
            ordered_results.append(match.results_json)
            outcome_pairs.append(
                (
                    match.results_json,
                    (
                        match.predicted_conversion_rate,
                        match.actual_conversion_rate,
                    ),
                )
            )

        findings_payload = aggregate_findings(
            ordered_results,
            min_severity=normalise_severity(None),
            top_n=normalise_top_n(None),
            architect=None,
        )
        outcomes_payload = aggregate_outcomes(
            [(p[1][0], p[1][1]) for p in outcome_pairs],
            outlier_threshold=normalise_outlier_threshold(None),
            sim_ids=list(by_id.keys()),
        )
        clusters_payload = aggregate_clusters(
            ordered_results,
            cluster_names=cluster_names,
            top_n=normalise_clusters_top_n(None),
        )
        bridge_payload = bridge_architect_accuracy(
            outcome_pairs,
            min_severity=normalise_bridge_severity(None),
            top_n=normalise_bridge_top_n(None),
        )
        summary = build_portfolio_summary(
            simulation_count=len(ordered_results),
            findings_payload=findings_payload,
            outcomes_payload=outcomes_payload,
            clusters_payload=clusters_payload,
            architect_accuracy_payload=bridge_payload,
        )

    # Metadata header — provenance so the file is self-
    # describing when reopened later.
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_count": summary.get("simulation_count", 0),
        "format_version": "1",
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        # JSON path — payload + metadata so machine consumers
        # can still surface provenance without parsing CSV.
        json_text = json.dumps(
            {"metadata": metadata, "portfolio": summary},
            default=str,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="thecee-portfolio.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = portfolio_to_csv(summary, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="thecee-portfolio.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


def _batch_overall_mean(
    results_jsons: object,
) -> float | None:
    """Mean of every cluster conversion rate across every sim.

    Used as the denominator for the drill-down's
    ``peer_comparison.batch_overall_mean``. Returns ``None``
    when no usable data exists (so the dashboard renders
    ``UNKNOWN`` instead of a misleading zero).
    """
    rates: list[float] = []
    for results in results_jsons:
        if not isinstance(results, dict):
            continue
        breakdown = results.get("cluster_breakdown") or {}
        if not isinstance(breakdown, dict):
            continue
        for raw in breakdown.values():
            if raw is None or isinstance(raw, bool):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            if 0.0 <= value <= 1.0:
                rates.append(value)
    if not rates:
        return None
    return sum(rates) / len(rates)


def _build_window_portfolio(
    db: Session,
    current_user: User,
    *,
    since: datetime | None,
    until: datetime | None,
    cluster_names: dict[str, str],
) -> dict:
    """Build the full portfolio-summary payload for one time
    window. Internal helper used by the trend route so both
    windows run the same DB query + sub-aggregate pipeline."""

    # Single DB round-trip per window: LEFT JOIN outcomes to
    # simulations, scoped to the current user. The optional
    # ``since`` / ``until`` filter narrows by Simulation.created_at.
    filters = [
        Project.user_id == current_user.id,
    ]
    if since is not None:
        filters.append(Simulation.created_at >= since)
    if until is not None:
        filters.append(Simulation.created_at < until)
    rows = (
        db.query(
            Simulation.id,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(*filters)
        .order_by(Outcome.created_at.desc())
        .all()
    )

    # Keep latest outcome per sim; build the two lists the
    # sub-aggregates need.
    by_id: dict[int, object] = {}
    for r in rows:
        if r.id in by_id:
            continue
        by_id[r.id] = r
    ordered_results: list[dict] = []
    outcome_pairs: list[
        tuple[dict | None, tuple[float | None, float | None]]
    ] = []
    for sid, match in by_id.items():
        ordered_results.append(match.results_json)
        outcome_pairs.append(
            (
                match.results_json,
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                ),
            )
        )

    # Run the four sub-aggregates (same path as portfolio-summary).
    findings_payload = aggregate_findings(
        ordered_results,
        min_severity=normalise_severity(None),
        top_n=normalise_top_n(None),
        architect=None,
    )
    outcomes_payload = aggregate_outcomes(
        [(p[1][0], p[1][1]) for p in outcome_pairs],
        outlier_threshold=normalise_outlier_threshold(None),
        sim_ids=list(by_id.keys()),
    )
    clusters_payload = aggregate_clusters(
        ordered_results,
        cluster_names=cluster_names,
        top_n=normalise_clusters_top_n(None),
    )
    bridge_payload = bridge_architect_accuracy(
        outcome_pairs,
        min_severity=normalise_bridge_severity(None),
        top_n=normalise_bridge_top_n(None),
    )
    return build_portfolio_summary(
        simulation_count=len(ordered_results),
        findings_payload=findings_payload,
        outcomes_payload=outcomes_payload,
        clusters_payload=clusters_payload,
        architect_accuracy_payload=bridge_payload,
    )


@router.get(
    "/portfolio-trend",
    response_model=PortfolioTrendOut,
    summary=(
        "Diff two portfolio summaries across time windows so the "
        "dashboard can render trend tiles"
    ),
    # Composite of TWO portfolio summaries → same cap.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_portfolio_trend(
    since: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Earlier window "
            "starts here. Optional."
        ),
    ),
    until: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Later window "
            "ends here (exclusive upper bound). Defaults to now."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioTrendOut:
    """Compare portfolio across two time windows.

    The earlier window runs from ``since`` up to ``until``. The
    later window runs from ``until`` up to "now" (UTC). Both
    windows' portfolios are computed independently, then the
    trend helper diffs them into per-metric deltas + an overall
    health-transition label so the dashboard can render "MAE
    dropped from 0.12 → 0.05 over the last 30 days · NEEDS_
    ATTENTION → HEALTHY".
    """
    try:
        since_dt = parse_since(since)
        until_dt = parse_since(until)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    now = datetime.now(tz=UTC)
    later_until = until_dt or now

    cluster_names = {
        cluster.cluster_id: cluster.name
        for cluster in _registry.all_clusters()
    }

    earlier_payload = _build_window_portfolio(
        db,
        current_user,
        since=since_dt,
        until=later_until,
        cluster_names=cluster_names,
    )
    later_payload = _build_window_portfolio(
        db,
        current_user,
        since=later_until,
        until=None,
        cluster_names=cluster_names,
    )
    trend = compute_portfolio_trend(earlier_payload, later_payload)
    return PortfolioTrendOut(**trend)


@router.get(
    "/cluster-drill-down",
    response_model=ClusterDrillDownOut,
    summary=(
        "Drill into a single cluster: profile + per-sim "
        "conversion history + aggregate stats"
    ),
    # DB read of N sim rows for one cluster — same cap as the
    # other aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_cluster_drill_down(
    cluster_id: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Cluster id (snake-case). Must match a registered "
            "cluster; otherwise the route returns 404."
        ),
    ),
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids, the "
            "drill-down returns the cluster profile only (no "
            "per-sim history)."
        ),
    ),
    outlier_threshold: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Absolute conversion-rate threshold above which a "
            "sim counts as an outlier. Default 0.10. Clamped "
            "to [0.0, 1.0]."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClusterDrillDownOut:
    """Per-cluster drill-down for the portfolio dashboard.

    Complements the cross-sim cluster aggregate: when the
    portfolio surfaces a laggard cluster (e.g.
    tier3_first_time_app_user consistently under 1% conversion),
    the founder clicks through and gets the cluster's full
    profile + every sim in the batch that saw this cluster +
    aggregate stats.
    """
    # Validate the cluster id against the registry — refuse early
    # so the dashboard can show a clear "unknown cluster" error
    # rather than a silent empty payload.
    definition = next(
        (
            c for c in _registry.all_clusters()
            if c.cluster_id == cluster_id
        ),
        None,
    )
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown cluster_id {cluster_id!r}",
        )

    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    threshold = normalise_drill_outlier(outlier_threshold)

    per_sim_conversions: list[
        tuple[int | None, object]
    ] = []
    if canonical_ids:
        rows = (
            db.query(
                Simulation.id,
                Simulation.results_json,
            )
            .join(Project, Simulation.project_id == Project.id)
            .filter(
                Simulation.id.in_(canonical_ids),
                Simulation.status == "COMPLETED",
                Project.user_id == current_user.id,
            )
            .all()
        )
        by_id: dict[int, dict] = {r.id: r.results_json for r in rows}
        # Preserve the user's requested order; missing sims
        # get ``None`` so the per-sim history still reflects
        # the batch.
        for sid in canonical_ids:
            breakdown = by_id.get(sid)
            if breakdown is None:
                per_sim_conversions.append((sid, None))
                continue
            cluster_breakdown = breakdown.get("cluster_breakdown") or {}
            per_sim_conversions.append(
                (sid, cluster_breakdown.get(cluster_id))
            )

    payload = build_cluster_drill_down(
        cluster_id,
        cluster_name=definition.name,
        cluster_description=definition.description,
        cluster_traits=dict(definition.base_traits),
        population_weight=definition.population_weight,
        dominant_behavior_pattern=definition.dominant_behavior_pattern,
        known_failure_modes=list(definition.known_failure_modes),
        product_affinities=list(definition.product_affinities),
        demographic_profile=dict(definition.demographic_profile),
        per_sim_conversions=per_sim_conversions,
        outlier_threshold=threshold,
        batch_overall_mean=_batch_overall_mean(by_id.values()),
    )
    return ClusterDrillDownOut(**payload)


@router.get(
    "/cluster-diff",
    response_model=ClusterDiffOut,
    summary=(
        "Side-by-side comparison of two clusters: per-trait "
        "deltas + aggregate deltas + similarity score"
    ),
    # DB read of N sim rows for two clusters — same cap as the
    # other drill-down endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_cluster_diff(
    cluster_a: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "First cluster id. Must match a registered cluster; "
            "otherwise the route returns 404."
        ),
    ),
    cluster_b: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Second cluster id. Must match a registered cluster; "
            "otherwise the route returns 404. ``cluster_a`` and "
            "``cluster_b`` must differ."
        ),
    ),
    ids: list[str] | None = Query(
        default=None,
        description=(
            "Optional batch of simulation ids. When supplied, "
            "the route computes aggregate stats (mean "
            "conversion, observation count, etc.) for each "
            "cluster across this batch. Without ids, the "
            "diff falls back to profile-only (no aggregate "
            "deltas)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClusterDiffOut:
    """Side-by-side comparison of two clusters.

    Pulls both cluster definitions from the registry,
    optionally runs the cluster drill-down on each side to
    compute aggregate stats across the user's batch, and
    emits a per-trait / per-metric diff with a similarity
    score.
    """
    # Validate both cluster ids against the registry. Unknown
    # id → 404 so the dashboard can show a clear error rather
    # than silently diff against missing clusters.
    def_a = next(
        (c for c in _registry.all_clusters() if c.cluster_id == cluster_a),
        None,
    )
    def_b = next(
        (c for c in _registry.all_clusters() if c.cluster_id == cluster_b),
        None,
    )
    if def_a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown cluster_id {cluster_a!r}",
        )
    if def_b is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown cluster_id {cluster_b!r}",
        )
    if cluster_a == cluster_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "cluster_a and cluster_b must differ — diffing "
                "a cluster against itself always returns "
                "similarity=1.0 and zero deltas"
            ),
        )

    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    cluster_a_aggregate: dict | None = None
    cluster_b_aggregate: dict | None = None
    if canonical_ids:
        rows = (
            db.query(Simulation.id, Simulation.results_json)
            .join(Project, Simulation.project_id == Project.id)
            .filter(
                Simulation.id.in_(canonical_ids),
                Simulation.status == "COMPLETED",
                Project.user_id == current_user.id,
            )
            .all()
        )
        by_id: dict[int, dict] = {r.id: r.results_json for r in rows}
        per_sim_a: list[
            tuple[int | None, object]
        ] = []
        per_sim_b: list[
            tuple[int | None, object]
        ] = []
        for sid in canonical_ids:
            breakdown = by_id.get(sid)
            cb = (
                breakdown.get("cluster_breakdown")
                if breakdown
                else None
            ) or {}
            per_sim_a.append((sid, cb.get(cluster_a)))
            per_sim_b.append((sid, cb.get(cluster_b)))

        threshold = normalise_drill_outlier(None)

        def _aggregate(per_sim):
            payload = build_cluster_drill_down(
                cluster_a if per_sim is per_sim_a else cluster_b,
                cluster_name=(
                    def_a.name if per_sim is per_sim_a else def_b.name
                ),
                per_sim_conversions=per_sim,
                outlier_threshold=threshold,
                batch_overall_mean=_batch_overall_mean(
                    by_id.values()
                ),
            )
            return payload["aggregate"]

        cluster_a_aggregate = _aggregate(per_sim_a)
        cluster_b_aggregate = _aggregate(per_sim_b)

    payload = build_cluster_diff(
        cluster_a,
        cluster_b,
        cluster_a_name=def_a.name,
        cluster_a_traits=dict(def_a.base_traits),
        cluster_a_aggregate=cluster_a_aggregate,
        cluster_a_product_affinities=list(def_a.product_affinities),
        cluster_b_name=def_b.name,
        cluster_b_traits=dict(def_b.base_traits),
        cluster_b_aggregate=cluster_b_aggregate,
        cluster_b_product_affinities=list(def_b.product_affinities),
    )
    return ClusterDiffOut(**payload)


@router.get(
    "/cluster-overlap-matrix",
    response_model=ClusterOverlapMatrixOut,
    summary=(
        "N×N similarity matrix across a list of clusters so "
        "the dashboard can render a consolidation heatmap"
    ),
    # DB read of N cluster definitions — same cap as the
    # other aggregate endpoints. Auth required so the cluster
    # taxonomy isn't anonymously enumerable.
    dependencies=[
        Depends(rate_limit(limit=30, window_s=60)),
        Depends(get_current_user),
    ],
)
def get_cluster_overlap_matrix(
    cluster_ids: list[str] = Query(
        ...,
        min_length=1,
        description=(
            "Cluster ids to include in the matrix. Repeat the "
            "param or pass comma-separated values. Order is "
            "preserved in the response. Capped at 25 ids."
        ),
    ),
    current_user: User = Depends(get_current_user),
):
    """Pairwise similarity matrix across N clusters."""
    canonical = _normalise_cluster_ids(cluster_ids, _MAX_MATRIX_CLUSTERS)
    entries = _build_cluster_overlap_entries(canonical)

    try:
        payload = build_cluster_overlap_matrix(entries)
    except ValueError as exc:
        # Defensive — the route layer is already validating
        # the cap; this catches any future helper-level guard.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return ClusterOverlapMatrixOut(**payload)


@router.get(
    "/cluster-overlap-matrix/export",
    response_class=StreamingResponse,
    summary=(
        "Export the cluster-overlap matrix as CSV (or JSON "
        "with ?format=json)"
    ),
    # Same registry read as the JSON overlap endpoint; cap
    # polling so a dashboard loop can't drive repeated
    # matrix builds.
    dependencies=[
        Depends(rate_limit(limit=30, window_s=60)),
        Depends(get_current_user),
    ],
)
def export_cluster_overlap_matrix(
    cluster_ids: list[str] = Query(
        ...,
        min_length=1,
        description=(
            "Cluster ids to include in the matrix. Repeat the "
            "param or pass comma-separated values. Order is "
            "preserved. Capped at 25 ids."
        ),
    ),
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly matrix; ``json`` returns the "
            "raw cluster-overlap payload. Unsupported values "
            "return a 400 response."
        ),
    ),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of the cluster-overlap matrix.

    Supports the same ``cluster_ids`` filter as
    ``GET /simulations/cluster-overlap-matrix``. Default ``format=csv``
    renders the summary, similarity matrix, pair summaries, and
    consolidation candidates as a multi-section spreadsheet. ``json``
    returns the raw payload for machine consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    canonical_ids = _normalise_cluster_ids(cluster_ids, _MAX_MATRIX_CLUSTERS)
    entries = _build_cluster_overlap_entries(canonical_ids)
    try:
        payload = build_cluster_overlap_matrix(entries)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "requested_ids": canonical_ids,
    }

    if fmt == "json":
        json_text = cluster_overlap_to_json(payload, metadata=metadata)
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="cluster-overlap-matrix.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = cluster_overlap_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="cluster-overlap-matrix.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


def _normalise_cluster_ids(
    cluster_ids: list[str],
    max_clusters: int,
) -> list[str]:
    """Normalise comma-separated cluster ids into a deduplicated list."""
    seen: set[str] = set()
    canonical: list[str] = []
    for raw in cluster_ids:
        if raw is None:
            continue
        for piece in str(raw).split(","):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.add(piece)
                canonical.append(piece)
    if not canonical:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "cluster_ids must supply at least one non-empty "
                "id"
            ),
        )
    if len(canonical) > max_clusters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"too many cluster_ids ({len(canonical)}); max "
                f"is {max_clusters}"
            ),
        )
    return canonical


def _build_cluster_overlap_entries(canonical_ids: list[str]) -> list[dict]:
    """Load cluster definitions in canonical order as matrix entries."""
    entries: list[dict] = []
    for cid in canonical_ids:
        definition = next(
            (c for c in _registry.all_clusters() if c.cluster_id == cid),
            None,
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown cluster_id {cid!r}",
            )
        entries.append({
            "cluster_id": definition.cluster_id,
            "cluster_name": definition.name,
            "traits": dict(definition.base_traits),
        })
    return entries


@router.get(
    "/cluster-trend",
    response_model=ClusterTrendOut,
    summary=(
        "Per-cluster conversion trend over time — monthly / "
        "weekly / daily bins"
    ),
    # DB read of N sim rows for one cluster — same cap as the
    # other drill-down endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_cluster_trend(
    cluster_id: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Cluster id (snake-case). Must match a registered "
            "cluster; otherwise the route returns 404."
        ),
    ),
    since: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "lower bound on Simulation.created_at."
        ),
    ),
    until: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "exclusive upper bound on Simulation.created_at."
        ),
    ),
    bin: str | None = Query(
        default=None,
        max_length=8,
        description=(
            "Bin granularity. ``month`` (default) / ``week`` "
            "/ ``day``. Anything else raises 400."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClusterTrendOut:
    """Per-cluster conversion-rate trend over time.

    Pulls the owned simulations for the current user (filtered
    by ``since`` / ``until``), groups them by creation
    date in ``month`` / ``week`` / ``day`` bins, and reports
    the mean conversion rate of ``cluster_id`` per bin plus an
    overall direction label.
    """
    definition = next(
        (
            c for c in _registry.all_clusters()
            if c.cluster_id == cluster_id
        ),
        None,
    )
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown cluster_id {cluster_id!r}",
        )

    try:
        since_dt = parse_since(since)
        until_dt = parse_since(until)
        effective_bin = normalise_trend_bin(bin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    filters = [
        Project.user_id == current_user.id,
        Simulation.status == "COMPLETED",
    ]
    if since_dt is not None:
        filters.append(Simulation.created_at >= since_dt)
    if until_dt is not None:
        filters.append(Simulation.created_at < until_dt)
    rows = (
        db.query(
            Simulation.created_at,
            Simulation.results_json,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(*filters)
        .order_by(Simulation.created_at.asc())
        .all()
    )

    payload = build_cluster_trend(
        cluster_id,
        [(r.created_at, r.results_json) for r in rows],
        bin_size=effective_bin,
    )
    return ClusterTrendOut(**payload)


@router.get(
    "/architect-bias-trend",
    response_model=ArchitectBiasTrendOut,
    summary=(
        "Per-architect |calibration_variance| trend over "
        "time — IMPROVING / DEGRADING / STABLE"
    ),
    # DB read of N sim rows for one architect — same cap as
    # the other trend endpoint.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_architect_bias_trend(
    architect_name: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Architect name (PascalCase). Must match a "
            "registered architect; otherwise the route "
            "returns 404."
        ),
    ),
    since: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "lower bound on Simulation.created_at."
        ),
    ),
    until: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "exclusive upper bound on Simulation.created_at."
        ),
    ),
    bin: str | None = Query(
        default=None,
        max_length=8,
        description=(
            "Bin granularity. ``month`` (default) / ``week`` "
            "/ ``day``. Anything else raises 400."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchitectBiasTrendOut:
    """Per-architect |calibration_variance| trend over time.

    Pulls the owned simulations for the current user
    (filtered by ``since`` / ``until``), joins with their
    outcomes + domain_findings, and groups the named
    architect's per-sim calibration variance (predicted −
    actual, taken only on sims where the architect flagged
    findings) by month / week / day.
    """
    architect_instance = _architect_registry.get(architect_name)
    if architect_instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown architect_name {architect_name!r}",
        )

    try:
        since_dt = parse_since(since)
        until_dt = parse_since(until)
        effective_bin = normalise_bias_bin(bin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    filters = [
        Project.user_id == current_user.id,
        Simulation.status == "COMPLETED",
    ]
    if since_dt is not None:
        filters.append(Simulation.created_at >= since_dt)
    if until_dt is not None:
        filters.append(Simulation.created_at < until_dt)
    rows = (
        db.query(
            Simulation.id,
            Simulation.created_at,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(*filters)
        .order_by(Outcome.created_at.desc())
        .all()
    )

    # Keep latest outcome per sim. The LEFT JOIN can produce
    # multiple rows per sim if a founder has submitted more than
    # one outcome; the ORDER BY Outcome.created_at DESC above
    # puts the newest outcome first, so we just take the first
    # row we see per Simulation.id.
    seen: set[int] = set()
    trend_rows: list[
        tuple[object, object, object, list[dict] | None]
    ] = []
    for r in rows:
        if r.created_at is None:
            # Sim without a created_at — can't bin it on the
            # trend timeline.
            continue
        if r.id in seen:
            continue
        seen.add(r.id)
        trend_rows.append(
            (
                r.created_at,
                r.predicted_conversion_rate,
                r.actual_conversion_rate,
                (
                    (r.results_json or {}).get("domain_findings")
                    or []
                ),
            )
        )

    payload = build_architect_bias_trend(
        architect_name,
        trend_rows,
        bin_size=effective_bin,
    )
    return ArchitectBiasTrendOut(**payload)


@router.get(
    "/findings-trend",
    response_model=FindingsTrendOut,
    summary=(
        "Per-bin findings-severity counts (CRITICAL / "
        "WARNING / INFO) so the dashboard can render "
        "'CRITICAL peaked on day X' trend tiles"
    ),
    # DB read of N sim rows — same cap as the other trend
    # endpoint.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_findings_trend(
    since: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "lower bound on Simulation.created_at."
        ),
    ),
    until: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "ISO 8601 timestamp (timezone-aware). Optional "
            "exclusive upper bound on Simulation.created_at."
        ),
    ),
    bin: str | None = Query(
        default=None,
        max_length=8,
        description=(
            "Bin granularity. ``day`` (default) / ``week`` "
            "/ ``month``. Anything else raises 400."
        ),
    ),
    min_severity: str | None = Query(
        default=None,
        max_length=16,
        description=(
            "Filter findings to >= this severity. "
            "``INFO`` (default) / ``WARNING`` / "
            "``CRITICAL``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FindingsTrendOut:
    """Per-bin findings-severity counts over time.

    Pulls the owned simulations for the current user
    (filtered by ``since`` / ``until``), groups their
    ``domain_findings`` by creation date in ``day`` /
    ``week`` / ``month`` bins, and reports the count of
    findings per severity per bin plus an overall
    direction label (IMPROVING / DEGRADING / STABLE)
    based on the CRITICAL-count delta between the first
    and last bins.
    """
    try:
        since_dt = parse_since(since)
        until_dt = parse_since(until)
        effective_bin = normalise_findings_bin(bin)
        effective_severity = normalise_findings_severity(
            min_severity
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    filters = [
        Project.user_id == current_user.id,
        Simulation.status == "COMPLETED",
    ]
    if since_dt is not None:
        filters.append(Simulation.created_at >= since_dt)
    if until_dt is not None:
        filters.append(Simulation.created_at < until_dt)
    rows = (
        db.query(Simulation.created_at, Simulation.results_json)
        .join(Project, Simulation.project_id == Project.id)
        .filter(*filters)
        .all()
    )

    payload = build_findings_trend(
        [
            (
                r.created_at,
                (r.results_json or {}).get("domain_findings") or [],
            )
            for r in rows
        ],
        min_severity=effective_severity,
        bin_size=effective_bin,
    )
    return FindingsTrendOut(**payload)


@router.get(
    "/project-portfolio-rollup",
    response_model=ProjectPortfolioRollupOut,
    summary=(
        "Per-project rollup so the dashboard's 'all my "
        "projects' view shows which project has the most "
        "sims, the most recent activity, and the worst "
        "calibration"
    ),
    # DB read of N sim rows + N outcome rows — same cap as
    # the other aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_project_portfolio_rollup(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids "
            "the rollup is empty."
        ),
    ),
    confidence_threshold: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "|predicted − actual| above this is counted as a "
            "miscalibrated sim. Default 0.02 (2pp). Clamped "
            "to [0.0, 1.0]."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectPortfolioRollupOut:
    """Per-project rollup across the user's batch."""
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return ProjectPortfolioRollupOut()

    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else 0.02
    )

    rows = (
        db.query(
            Project.id,
            Project.title,
            Simulation.id,
            Simulation.created_at,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
        )
        .select_from(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .filter(
            Simulation.id.in_(canonical_ids),
            Simulation.status == "COMPLETED",
            Project.user_id == current_user.id,
        )
        .order_by(Simulation.id.asc(), Outcome.created_at.desc())
        .all()
    )

    # Dedupe to the latest outcome per sim.
    seen: set[int] = set()
    rollup_rows: list[tuple] = []
    for r in rows:
        if r[2] in seen:
            continue
        seen.add(r[2])
        rollup_rows.append(
            (r[0], r[1], r[2], r[3], r[4], r[5])
        )

    payload = build_project_portfolio_rollup(
        rollup_rows,
        confidence_threshold=threshold,
    )
    payload["confidence_threshold"] = threshold
    return ProjectPortfolioRollupOut(**payload)


@router.get(
    "/sim-diff",
    response_model=SimDiffOut,
    summary=(
        "Side-by-side comparison of two sims — findings + "
        "conversion + per-metric deltas"
    ),
    # DB read of 2 sim rows — same cap as the other
    # aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_sim_diff(
    sim_a: int = Query(
        ...,
        ge=1,
        description=(
            "First sim id. Must be an owned, COMPLETED sim."
        ),
    ),
    sim_b: int = Query(
        ...,
        ge=1,
        description=(
            "Second sim id. Must differ from sim_a."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimDiffOut:
    """Side-by-side comparison of two sims.

    Validates both ids against the user's owned set (400 on
    unknown id or equal ids), fetches the data, and runs the
    helper. Returns metadata + findings diff + conversion
    diff + per-metric rows + a one-line summary.
    """
    if sim_a == sim_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "sim_a and sim_b must differ — diffing a sim "
                "against itself always returns zero deltas"
            ),
        )

    rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.status,
            Simulation.created_at,
            Simulation.results_json,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_([sim_a, sim_b]),
            Simulation.status == "COMPLETED",
            Project.user_id == current_user.id,
        )
        .order_by(Simulation.id.asc(), Outcome.created_at.desc())
        .all()
    )

    by_id: dict[int, dict] = {}
    for r in rows:
        if r.id in by_id:
            continue
        by_id[r.id] = {
            "project_id": r.project_id,
            "status": r.status,
            "created_at": r.created_at,
            "predicted_conversion_rate": r.predicted_conversion_rate,
            "actual_conversion_rate": r.actual_conversion_rate,
            "domain_findings": (
                (r.results_json or {}).get("domain_findings") or []
            ),
        }

    if sim_a not in by_id or sim_b not in by_id:
        missing = []
        if sim_a not in by_id:
            missing.append(f"sim_a={sim_a}")
        if sim_b not in by_id:
            missing.append(f"sim_b={sim_b}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "unknown or non-owned sim(s): "
                + ", ".join(missing)
            ),
        )

    payload = build_sim_diff(
        sim_a, by_id[sim_a],
        sim_b, by_id[sim_b],
    )
    return SimDiffOut(**payload)


@router.get(
    "/outlier-detection",
    response_model=OutlierDetectionOut,
    summary=(
        "Flag sims whose |predicted − actual| is more than "
        "z_threshold σ from the batch mean so the founder "
        "can separate anomalies from systemic drift"
    ),
    # DB read of N sim + outcome rows — same cap as the
    # other aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_outlier_detection(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids the "
            "endpoint returns an empty payload."
        ),
    ),
    z_threshold: float | None = Query(
        default=None,
        ge=0.5,
        le=10.0,
        description=(
            "|variance| z-score cutoff. Default 3σ (≈0.3% of "
            "a normal distribution). Clamped to [0.5, 10.0]."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutlierDetectionOut:
    """Per-sim outlier detection by |variance| z-score.

    Joins simulations + outcomes scoped to the current user,
    builds (sim_id, predicted, actual) tuples, and runs the
    helper. Returns the outliers list + batch stats so the
    dashboard can render "X of Y sims flagged" without
    recomputing.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return OutlierDetectionOut()

    threshold = normalise_z_threshold(z_threshold)

    rows = (
        db.query(
            Simulation.id,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Simulation.status == "COMPLETED",
            Project.user_id == current_user.id,
        )
        .all()
    )

    payload = build_outlier_detection(
        [(r[0], r[1], r[2]) for r in rows],
        z_threshold=threshold,
    )
    return OutlierDetectionOut(**payload)


def _fetch_calibration_health_rows(
    db: Session,
    user_id: int,
    canonical_ids: list[int],
) -> list[tuple[object, object, object, list[dict] | None]]:
    """Fetch sim/outcome rows for calibration-health aggregation.

    The query keeps the latest outcome per simulation (the LEFT JOIN
    is ordered by outcome ``created_at`` descending, so the first row
    per simulation is the newest outcome). It is scoped to simulations
    owned by ``user_id`` and accepts a pre-parsed, capped ID list.
    """
    rows = (
        db.query(
            Simulation.id,
            Simulation.created_at,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Simulation.results_json,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Simulation.status == "COMPLETED",
            Project.user_id == user_id,
        )
        .order_by(Simulation.created_at.asc(), Outcome.created_at.desc())
        .all()
    )

    # Keep latest outcome per sim. The LEFT JOIN produces one
    # row per (sim, outcome) pair; with the ORDER BY above the
    # newest outcome for each sim is the FIRST row we see, so
    # the ``seen`` set keeps one row per Simulation.id.
    seen: set[int] = set()
    health_rows: list[tuple[object, object, object, list[dict] | None]] = []
    for r in rows:
        if r.created_at is None:
            # can't build a health row without created_at.
            continue
        if r.id in seen:
            continue
        seen.add(r.id)
        findings = (
            (r.results_json or {}).get("domain_findings") or []
        )
        health_rows.append(
            (
                r.created_at,
                r.predicted_conversion_rate,
                r.actual_conversion_rate,
                findings,
            )
        )
    return health_rows


@router.get(
    "/calibration-health",
    response_model=CalibrationHealthOut,
    summary=(
        "Single-payload calibration health check — overall "
        "label + top miscalibrated architect + 7d/30d/90d "
        "trend buckets"
    ),
    # DB read of N sim + outcome rows — same cap as the
    # other aggregate endpoints.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_calibration_health(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids the "
            "endpoint returns INSUFFICIENT_DATA."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalibrationHealthOut:
    """Single-payload calibration health check.

    Joins simulations + outcomes + domain_findings scoped
    to the current user, builds the trend buckets
    (created_at → |variance|) and the architect-accuracy
    bridge payload, and fuses them into one health-check
    payload.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return CalibrationHealthOut()

    health_rows = _fetch_calibration_health_rows(
        db,
        current_user.id,
        canonical_ids,
    )

    payload = build_calibration_health(health_rows)
    return CalibrationHealthOut(**payload)


@router.get(
    "/calibration-health/export",
    response_class=StreamingResponse,
    summary=(
        "Export the calibration-health payload as CSV (or JSON "
        "with ?format=json)"
    ),
    # Same DB read cost as the JSON health endpoint; cap polling
    # so a dashboard loop can't drive repeated N-sim scans.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_calibration_health(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/calibration-health``. Optional; "
            "without ids the export contains an empty "
            "INSUFFICIENT_DATA health payload."
        ),
    ),
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the "
            "raw calibration-health payload. Unsupported values "
            "return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of the user's calibration-health report.

    Supports the same ``ids`` filter as ``GET /simulations/calibration-health``.
    Default ``format=csv`` renders the summary, trend buckets, and architect
    recommendation counts as a multi-section spreadsheet. ``format=json``
    returns the raw payload for machine consumers.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if canonical_ids:
        health_rows = _fetch_calibration_health_rows(
            db,
            current_user.id,
            canonical_ids,
        )
        payload = build_calibration_health(health_rows)
    else:
        payload = build_calibration_health([])

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "requested_ids": canonical_ids,
    }

    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )
    if fmt == "json":
        json_text = json.dumps(
            {"metadata": metadata, "calibration_health": payload},
            default=str,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="calibration-health.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = calibration_health_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="calibration-health.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/portfolio-narrative",
    response_model=PortfolioNarrativeOut,
    summary=(
        "Single-payload narrative that composes the "
        "portfolio summary, calibration health, architect "
        "leaderboard, and outlier detection outputs into "
        "one founder-readable paragraph + structured signals"
    ),
    # Composite of 4 sub-helpers — same cap.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_portfolio_narrative(
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids "
            "the narrative is empty."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioNarrativeOut:
    """Single-payload narrative.

    Runs the four sub-helpers (portfolio_summary,
    calibration_health, architect_leaderboard,
    outlier_detection) on the same batch, then composes
    them into one narrative + key_signals + recommended_actions
    payload. The route pays the cost of all four queries
    once and amortises the round-trip cost across the
    composite.
    """
    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if not canonical_ids:
        return PortfolioNarrativeOut()

    # Cache hit → short-circuit the JOIN + four sub-helpers.
    # Key is namespaced by user + sorted canonical ids so
    # two distinct batches never collide and one tenant
    # never sees another tenant's payload.
    cached = cache_get_json(
        namespace=_PORTFOLIO_NARRATIVE_CACHE_NAMESPACE,
        params={"ids": canonical_ids},
        user_id=current_user.id,
    )
    if cached is not None:
        return PortfolioNarrativeOut(**cached)

    # Single JOIN that pulls (sim_id, created_at, results_json,
    # latest outcome) once. Each sub-helper then reuses the
    # data without re-querying.
    rows = (
        db.query(
            Simulation.id,
            Simulation.created_at,
            Simulation.results_json,
            Simulation.status,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.created_at,
        )
        .outerjoin(
            Outcome, Outcome.simulation_id == Simulation.id,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id.in_(canonical_ids),
            Project.user_id == current_user.id,
        )
        .order_by(Simulation.id.asc(), Outcome.created_at.desc())
        .all()
    )

    # Dedupe to the latest outcome per sim.
    by_id: dict[int, object] = {}
    for r in rows:
        if r.id in by_id:
            continue
        by_id[r.id] = r

    ordered_results: list[dict] = []
    outcome_pairs: list[
        tuple[list[dict], tuple[float | None, float | None]]
    ] = []
    health_rows: list[tuple] = []
    for sid in canonical_ids:
        match = by_id.get(sid)
        if match is None:
            continue
        if match.status != "COMPLETED":
            continue
        ordered_results.append(match.results_json)
        outcome_pairs.append(
            (
                (match.results_json or {}).get("domain_findings")
                or [],
                (
                    match.predicted_conversion_rate,
                    match.actual_conversion_rate,
                ),
            )
        )
        health_rows.append(
            (
                match.created_at,
                match.predicted_conversion_rate,
                match.actual_conversion_rate,
                (match.results_json or {}).get("domain_findings")
                or [],
            )
        )

    # Build the four sub-payloads.
    cluster_names = {
        c.cluster_id: c.name
        for c in _registry.all_clusters()
    }
    findings_payload = aggregate_findings(
        ordered_results,
        min_severity=normalise_severity(None),
        top_n=normalise_top_n(None),
        architect=None,
    )
    outcomes_payload = aggregate_outcomes(
        [(p[1][0], p[1][1]) for p in outcome_pairs],
        outlier_threshold=normalise_outlier_threshold(None),
        sim_ids=list(by_id.keys()),
    )
    clusters_payload = aggregate_clusters(
        ordered_results,
        cluster_names=cluster_names,
        top_n=normalise_clusters_top_n(None),
    )
    bridge_payload = bridge_architect_accuracy(outcome_pairs)
    portfolio_summary = build_portfolio_summary(
        simulation_count=len(ordered_results),
        findings_payload=findings_payload,
        outcomes_payload=outcomes_payload,
        clusters_payload=clusters_payload,
        architect_accuracy_payload=bridge_payload,
    )
    calibration_health = build_calibration_health(health_rows)
    architect_leaderboard = build_architect_leaderboard(
        bridge_payload.get("by_architect"),
    )

    # Outlier detection needs (sim_id, predicted, actual) tuples.
    outlier_rows = [
        (r.id, r.predicted_conversion_rate, r.actual_conversion_rate)
        for r in by_id.values()
        if r.status == "COMPLETED"
    ]
    outlier_detection = build_outlier_detection(
        outlier_rows,
        z_threshold=normalise_z_threshold(None),
    )

    payload = build_portfolio_narrative(
        portfolio_summary=portfolio_summary,
        calibration_health=calibration_health,
        architect_leaderboard=architect_leaderboard,
        outlier_detection=outlier_detection,
    )
    # Populate cache so the next dashboard poll within the
    # 30s window short-circuits the JOIN + four sub-helpers.
    cache_set_json(
        namespace=_PORTFOLIO_NARRATIVE_CACHE_NAMESPACE,
        params={"ids": canonical_ids},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_PORTFOLIO_NARRATIVE_CACHE_TTL_S,
    )
    return PortfolioNarrativeOut(**payload)


@router.get(
    "/architect-drill-down",
    response_model=ArchitectDrillDownOut,
    summary=(
        "Drill into a single architect: profile + per-sim finding "
        "history + bias / stability / recommendation"
    ),
    # DB read of N sim rows for one architect — same cap as the
    # other drill-down endpoint.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_architect_drill_down(
    architect_name: str = Query(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Architect name (PascalCase). Must match a registered "
            "architect; otherwise the route returns 404."
        ),
    ),
    ids: list[str] | None = Query(
        default=None,
        description=(
            "One or more simulation ids. Same parser as "
            "``/simulations/batch``. Optional; without ids, the "
            "drill-down returns the architect profile only."
        ),
    ),
    outlier_finding_threshold: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Per-sim finding-count threshold above which the "
            "sim is flagged as an outlier. Default 5."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchitectDrillDownOut:
    """Per-architect drill-down for the portfolio dashboard.

    Complements the cross-sim architect-accuracy bridge: when a
    biased architect surfaces (TIGHTEN / LOOSEN in the bridge),
    the founder clicks through and gets the architect's full
    profile + every sim in the batch where it flagged +
    aggregate stats + bias / stability / recommendation.
    """
    # Validate the architect name against the registry — refuse
    # early so the dashboard can show a clear "unknown
    # architect" error rather than a silent empty payload.
    architect_instance = _architect_registry.get(architect_name)
    if architect_instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown architect_name {architect_name!r}",
        )

    try:
        canonical_ids = parse_id_list(ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    threshold = (
        outlier_finding_threshold
        if outlier_finding_threshold is not None
        else 5
    )

    per_sim_findings: list[
        tuple[int | None, list[dict]]
    ] = []
    if canonical_ids:
        rows = (
            db.query(Simulation.id, Simulation.results_json)
            .join(Project, Simulation.project_id == Project.id)
            .filter(
                Simulation.id.in_(canonical_ids),
                Simulation.status == "COMPLETED",
                Project.user_id == current_user.id,
            )
            .all()
        )
        by_id: dict[int, list[dict]] = {
            r.id: (
                (r.results_json or {}).get("domain_findings")
                or []
            )
            for r in rows
        }
        # Preserve the user's requested order; missing sims
        # get an empty findings list so the per-sim history still
        # reflects the batch.
        for sid in canonical_ids:
            per_sim_findings.append(
                (sid, by_id.get(sid, []))
            )

    # Compute batch_overall |calibration_variance| by running
    # the bridge on this same batch — keeps the peer comparison
    # consistent with the dashboard's other surfaces.
    calibration_variance: float | None = None
    calibration_direction: str = "INSUFFICIENT_DATA"
    batch_overall_abs_variance: float | None = None
    if canonical_ids:
        # Pull outcomes for the same batch.
        outcome_rows = (
            db.query(
                Simulation.id,
                Outcome.predicted_conversion_rate,
                Outcome.actual_conversion_rate,
                Outcome.created_at,
            )
            .outerjoin(
                Outcome, Outcome.simulation_id == Simulation.id,
            )
            .join(Project, Simulation.project_id == Project.id)
            .filter(
                Simulation.id.in_(canonical_ids),
                Project.user_id == current_user.id,
            )
            .order_by(Outcome.created_at.desc())
            .all()
        )
        # Build (results_json, (predicted, actual)) pairs in user
        # order, keeping latest outcome per sim.
        seen: set[int] = set()
        outcome_pairs: list[
            tuple[list[dict], tuple[float | None, float | None]]
        ] = []
        for sid in canonical_ids:
            if sid in seen:
                continue
            seen.add(sid)
            match = next(
                (r for r in outcome_rows if r.id == sid), None
            )
            if match is None:
                outcome_pairs.append(([], (None, None)))
                continue
            outcome_pairs.append(
                (
                    (by_id.get(sid) or []),
                    (
                        match.predicted_conversion_rate,
                        match.actual_conversion_rate,
                    ),
                )
            )

        bridge = bridge_architect_accuracy(outcome_pairs)
        for row in bridge.get("by_architect") or []:
            if (
                str(row.get("architect_name", "")).lower()
                == architect_name.lower()
            ):
                calibration_variance = row.get(
                    "calibration_variance"
                )
                calibration_direction = row.get(
                    "calibration_direction",
                    "INSUFFICIENT_DATA",
                )
                break
        # Batch overall = mean of |variance| across all
        # architects in this batch's bridge output.
        variances_abs = [
            abs(r["calibration_variance"])
            for r in (bridge.get("by_architect") or [])
            if r.get("calibration_variance") is not None
        ]
        if variances_abs:
            batch_overall_abs_variance = (
                sum(variances_abs) / len(variances_abs)
            )

    payload = build_architect_drill_down(
        architect_name,
        product_types=list(architect_instance.product_types),
        per_sim_findings=per_sim_findings,
        calibration_variance=calibration_variance,
        calibration_direction=calibration_direction,
        outlier_finding_threshold=threshold,
        batch_overall_abs_variance=batch_overall_abs_variance,
    )
    return ArchitectDrillDownOut(**payload)


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

    cutoff = datetime.now(UTC) - timedelta(hours=72)
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
        "live_progress": progress_bridge.is_running(),
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

    env_params, assumptions = _load_what_if_context(sim, db)

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


@router.post(
    "/{simulation_id}/what-if/batch",
    response_model=WhatIfBatchOut,
    summary="Compare multiple what-if scenarios in one ranked call",
    responses=_JSON_200,
    # Heavy Markov recomputation over the existing results + N scenario
    # inputs; cap at 10/min/IP so a single actor can't grind the endpoint.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def post_what_if_batch(
    payload: WhatIfBatchRequest,
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatIfBatchOut:
    """
    Batch what-if scenario simulator.

    Accepts one to twenty scenarios in a single request, projects each one
    against the same completed simulation, and returns a ranked comparison
    (best/worst deltas, aggregate summary, full per-scenario payloads).

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

    env_params, assumptions = _load_what_if_context(sim, db)

    return build_what_if_batch(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
        scenarios=payload.scenarios,
    )


@router.post(
    "/{simulation_id}/what-if/batch/export",
    response_class=StreamingResponse,
    summary="Export a batch what-if comparison as CSV, JSON, or Markdown",
    # Mirrors the batch what-if compute cost; cap path-spam at 10/min/IP.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def export_what_if_batch(
    payload: WhatIfBatchRequest,
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw batch "
            "payload; ``md`` returns a founder-facing Markdown brief."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export a batch what-if scenario comparison.

    Default ``format=csv`` renders the batch payload as a multi-section
    spreadsheet (summary, ranked scenarios, best/worst blocks). ``json``
    returns the raw ``WhatIfBatchOut`` document for machine consumers, and
    ``md`` returns a concise Markdown brief for sharing with a team.

    Reuses the same batch projection as ``POST /what-if/batch`` — the
    response body is just a different serialization of that result.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; "
                "expected 'csv', 'json', or 'md'"
            ),
        )

    result = post_what_if_batch(
        payload=payload,
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": result.project_id,
    }

    if fmt == "json":
        body = what_if_batch_to_json(result, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="what-if-batch-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "md":
        body = what_if_batch_to_markdown(result, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="what-if-batch-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = what_if_batch_to_csv(result, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="what-if-batch-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
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
    "/{simulation_id}/funnel-diagnosis/export",
    response_class=StreamingResponse,
    summary=(
        "Export the funnel diagnosis as CSV, JSON, or Markdown"
    ),
    # Same DB read cost as the JSON funnel-diagnosis endpoint; cap polling
    # so a dashboard loop can't drive repeated reads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_funnel_diagnosis(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "funnel-diagnosis payload; ``md`` returns a founder-facing "
            "Markdown brief. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export a simulation's funnel diagnosis as CSV, JSON, or Markdown.

    Default ``format=csv`` renders the summary, per-stage diagnosis,
    cluster drag, drop triggers, and recommendations as a multi-section
    spreadsheet. ``json`` returns the raw payload for machine consumers,
    and ``md`` returns a founder-facing Markdown brief.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; "
                "expected 'csv', 'json', or 'md'"
            ),
        )

    payload = get_funnel_diagnosis(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id)
        .first()
    )
    project_name = project.title if project else None

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "md":
        md_text = funnel_diagnosis_to_markdown(
            payload,
            simulation_id=simulation_id,
            project_id=payload.project_id,
            project_name=project_name,
            metadata=metadata,
        )
        body = md_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="funnel-diagnosis-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "json":
        body = funnel_diagnosis_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="funnel-diagnosis.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = funnel_diagnosis_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="funnel-diagnosis.csv"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
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
    "/{simulation_id}/market-concentration",
    response_model=MarketConcentrationOut,
    summary="Measure how concentrated projected demand is across consumer clusters",
    responses=_JSON_200,
)
def get_market_concentration(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarketConcentrationOut:
    """
    Build a demand-concentration read from completed results:

      * demand share = population_weight × conversion_rate, normalised
      * HHI + effective segments + top-N shares + fragility verdict
      * founder-facing recommendations for diversifying demand risk

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
                f"Simulation is {sim.status} — market concentration requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

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

    return build_market_concentration(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        cluster_summaries=summaries or None,
        cluster_registry=registry,
    )


@router.get(
    "/{simulation_id}/unit-economics",
    response_model=UnitEconomicsOut,
    summary="Unit economics: LTV, CAC, payback and margin health per consumer cluster",
    responses=_JSON_200,
)
def get_unit_economics(
    simulation_id: int,
    gross_margin: float = Query(0.60, ge=0.0, le=1.0),
    purchase_frequency_per_year: float = Query(12.0, ge=1.0),
    assumed_cac: float = Query(0.0, ge=0.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnitEconomicsOut:
    """Build the per-customer economics read (see :func:`_build_unit_economics_payload`)."""
    return _build_unit_economics_payload(
        simulation_id=simulation_id,
        current_user_id=current_user.id,
        db=db,
        gross_margin=gross_margin,
        purchase_frequency_per_year=purchase_frequency_per_year,
        assumed_cac=assumed_cac,
    )


def _build_unit_economics_payload(
    simulation_id: int,
    current_user_id: int,
    db: Session,
    gross_margin: float = 0.60,
    purchase_frequency_per_year: float = 12.0,
    assumed_cac: float = 0.0,
) -> UnitEconomicsOut:
    """Compute a complete unit-economics payload for an owned simulation."""
    sim = _get_owned_simulation(simulation_id, current_user_id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation is {sim.status} — unit economics requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS

    # Recompute the deterministic architect stack for this product type so
    # per-cluster price ceilings, survival curves and channel CAC multipliers
    # are available even though regular simulation runs only persist aggregate
    # results. No DB writes are performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=[],
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_unit_economics(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        average_order_value=aov,
        gross_margin=gross_margin,
        purchase_frequency_per_year=purchase_frequency_per_year,
        assumed_cac=assumed_cac,
    )


@router.get(
    "/{simulation_id}/unit-economics/export",
    response_class=StreamingResponse,
    summary=(
        "Export the unit-economics analysis as CSV (or JSON with "
        "?format=json)"
    ),
    # Same DB read cost as the JSON unit-economics endpoint; cap polling
    # so a dashboard loop can't drive repeated Conductor recomputes.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_unit_economics(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "unit-economics payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    gross_margin: float = Query(0.60, ge=0.0, le=1.0),
    purchase_frequency_per_year: float = Query(12.0, ge=1.0),
    assumed_cac: float = Query(0.0, ge=0.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a simulation's unit-economics analysis.

    Supports the same ``gross_margin`` / ``purchase_frequency_per_year`` /
    ``assumed_cac`` inputs as ``GET /simulations/{id}/unit-economics``.
    Default ``format=csv`` renders the summary, per-cluster economics, CAC
    and price scenarios, and recommendations as a multi-section spreadsheet.
    ``format=json`` returns the raw payload for machine consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    payload = _build_unit_economics_payload(
        simulation_id=simulation_id,
        current_user_id=current_user.id,
        db=db,
        gross_margin=gross_margin,
        purchase_frequency_per_year=purchase_frequency_per_year,
        assumed_cac=assumed_cac,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "json":
        json_text = json.dumps(
            {"metadata": metadata, "unit_economics": payload.model_dump()},
            default=str,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="unit-economics.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = unit_economics_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="unit-economics.csv"',
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/pricing-optimization",
    response_model=PricingOptimizationOut,
    summary=(
        "Pricing optimization: demand curve, revenue-optimal price and "
        "elasticity"
    ),
    responses=_JSON_200,
)
def get_pricing_optimization(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PricingOptimizationOut:
    """
    Build a deterministic pricing-optimization read from completed results:

      * AOV-relative demand curve (price point -> demand-weighted conversion)
      * revenue-optimal price and the revenue lift vs the current price
      * recommended price (highest price retaining >=50% of base demand)
      * arc elasticity around the current price
      * per-cluster willingness-to-pay ceilings and at-ceiling flags

    Pure post-hoc analytics — no Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — pricing optimization requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS

    # Recompute the deterministic architect stack for this product type so
    # per-cluster price ceilings and will-pay probabilities are available
    # even though regular simulation runs only persist aggregate results.
    # No DB writes are performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=[],
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_pricing_optimization(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        average_order_value=aov,
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
    "/{simulation_id}/sensitivity/export",
    response_class=StreamingResponse,
    summary=(
        "Export the sensitivity analysis as CSV (or JSON with "
        "?format=json)"
    ),
    # Same DB read + Markov recompute cost as the JSON sensitivity
    # endpoint; cap polling so a dashboard loop can't drive repeated
    # scenario recomputes.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_sensitivity_analysis(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "sensitivity payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a simulation's sensitivity analysis.

    Computes the same payload as ``GET /simulations/{id}/sensitivity``,
    then renders it as CSV (default) or JSON. The CSV includes the
    summary, one row per assumption, and the recommendation list so a
    founder can prioritize which assumptions to validate in a planning
    tool.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    payload = get_sensitivity_analysis(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "json":
        body = sensitivity_to_json(payload, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="sensitivity.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = sensitivity_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="sensitivity.csv"',
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/feature-prioritization",
    response_model=FeaturePrioritizationOut,
    summary=(
        "Prioritize features by demand-weighted adoption, upside, and "
        "founder brief alignment"
    ),
    responses=_JSON_200,
)
def get_feature_prioritization(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeaturePrioritizationOut:
    """
    Deterministic feature-prioritization read from a completed run's
    ``FeatureAdoptionArchitect`` metrics:

      * nine modeled feature dimensions ranked by validated upside
        (adoption^2 x unserved headroom, product-type strategic boosts)
      * per-cluster feature-depth profiles (ADVANCED / MAINSTREAM /
        LAGGING segments)
      * the founder's declared brief features mapped onto the modeled
        dimensions by keyword
      * adoption-risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Returns
    ``INSUFFICIENT_DATA`` for product types whose conductor stack does not
    model feature adoption (hardware, marketplace, d2c, ...).
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
                f"Simulation is {sim.status} — feature prioritization "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS

    # Recompute the deterministic architect stack for this product type so
    # per-cluster feature-adoption metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=[],
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    brief_features: list[str] = []
    project = (
        db.query(Project)
        .filter(Project.id == sim.project_id)
        .first()
    )
    if project is not None and project.brief_features_json:
        try:
            parsed = json.loads(project.brief_features_json)
            if isinstance(parsed, list):
                brief_features = [
                    str(feature).strip()
                    for feature in parsed
                    if str(feature).strip()
                ][:5]
        except (ValueError, TypeError):
            brief_features = []

    return build_feature_prioritization(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
        brief_features=brief_features,
    )


@router.get(
    "/{simulation_id}/feature-prioritization/export",
    response_class=StreamingResponse,
    summary=(
        "Export feature prioritization as CSV, JSON, or Markdown"
    ),
    # Same DB read + conductor recompute cost as the JSON feature
    # prioritization endpoint; cap polling so a dashboard loop can't
    # drive repeated scenario recomputes.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_feature_prioritization(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a multi-section "
            "spreadsheet; ``json`` returns the raw feature-prioritization "
            "payload; ``md`` returns a founder-facing Markdown brief. "
            "Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the feature-prioritization read for a completed simulation."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; "
                "expected 'csv', 'json', or 'md'"
            ),
        )

    payload = get_feature_prioritization(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id)
        .first()
    )
    project_name = project.title if project else None

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "json":
        body = feature_prioritization_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="feature-prioritization-'
                    f'{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    if fmt == "md":
        md_text = feature_prioritization_to_markdown(
            payload,
            simulation_id=simulation_id,
            project_id=payload.project_id,
            project_name=project_name,
            metadata=metadata,
        )
        body = md_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="feature-prioritization-'
                    f'{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = feature_prioritization_to_csv(
        payload,
        metadata=metadata,
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="feature-prioritization-'
                f'{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/activation-funnel",
    response_model=ActivationFunnelOut,
    summary=(
        "Activation funnel: first-run completion, blockers, and "
        "highest-impact activation levers"
    ),
    responses=_JSON_200,
)
def get_activation_funnel(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActivationFunnelOut:
    """
    Deterministic activation-funnel read from a completed run's
    ``OnboardingArchitect`` metrics:

      * population-weighted activation rate, time-to-first-value tolerance,
        empty-state bounce, and friction aggregates
      * per-cluster activation tiers (STRONG / MODERATE / WEAK / CRITICAL)
      * per-cluster primary activation blocker (completion, empty state,
        identity verification, mandatory profile, mobile gap, permission
        timing, time-to-value) with a market-level blocker distribution
      * ranked activation levers by the share of the covered market they
        touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Onboarding
    metrics are recomputed from the project's visible assumptions so
    complexity signals from the brief shape the read. Returns
    ``INSUFFICIENT_DATA`` for product types whose conductor stack does not
    model first-run onboarding (hardware, d2c, ...).
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
                f"Simulation is {sim.status} — activation-funnel analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape OnboardingArchitect's
    # complexity signal; feed them through so the recomputed read matches
    # the actual run instead of defaulting to neutral complexity.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster onboarding metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_activation_funnel(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/virality-growth",
    response_model=ViralityGrowthOut,
    summary=(
        "Virality growth: word-of-mouth coefficient, viral tiers, "
        "growth blockers, and highest-impact growth levers"
    ),
    responses=_JSON_200,
)
def get_virality_growth(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ViralityGrowthOut:
    """
    Deterministic virality-growth read from a completed run's
    ``ViralityArchitect`` metrics:

      * population-weighted viral coefficient (K), organic referral
        trigger, invite completion, incentive quality, word-of-mouth
        coefficient, content virality, community participation, and the
        network-effect threshold
      * per-cluster growth tiers (VIRAL / PROMISING / EMERGING / WEAK)
      * per-cluster primary growth blocker (organic trigger, invite
        completion, incentive quality, word of mouth, content virality,
        community) with a market-level blocker distribution
      * ranked growth levers by the share of the covered market where the
        underlying input is below a healthy threshold, plus risk flags
        and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Virality
    metrics are recomputed from the project's visible assumptions so
    sharing signals from the brief shape the read. Returns
    ``INSUFFICIENT_DATA`` for product types whose conductor stack does not
    model word-of-mouth growth (enterprise software, iot hardware,
    wearable, b2b hardware, smart home, ...).
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
                f"Simulation is {sim.status} — virality-growth analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape ViralityArchitect's
    # satisfaction and sharing signals; feed them through so the
    # recomputed read matches the actual run instead of defaulting to
    # neutral growth inputs.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster virality metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_virality_growth(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/distribution-channels",
    response_model=DistributionChannelsOut,
    summary=(
        "Distribution channels: access readiness, channel blockers, "
        "and highest-impact distribution levers"
    ),
    responses=_JSON_200,
)
def get_distribution_channels(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistributionChannelsOut:
    """
    Deterministic distribution-channel read from a completed run's
    ``DistributionChannelArchitect`` metrics:

      * population-weighted accessibility multiplier, online
        preference, try-before-buy requirement, influencer dependency,
        cashback/loyalty sensitivity, delivery days required, and the
        four platform preferences (Amazon, Flipkart, brand direct,
        offline)
      * per-cluster channel tiers (OMNICHANNEL / ONLINE /
        LIMITED_ACCESS / ACCESS_GAP)
      * per-cluster primary distribution blocker (distribution access,
        try-before-buy, influencer verification, cashback/loyalty,
        delivery speed, platform presence) with a market-level blocker
        distribution
      * ranked distribution levers by the share of the covered market
        where the underlying input is below a healthy threshold, plus
        risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes.
    Distribution metrics are recomputed from the project's visible
    assumptions so offline / retail / store signals from the brief shape
    the read. Returns ``INSUFFICIENT_DATA`` for product types whose
    conductor stack does not model physical distribution
    (saas, marketplace, mobile_app, developer_tool,
    enterprise_software, consumer_app, d2c, b2b_marketplace,
    productivity_tool, ...).
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
                f"Simulation is {sim.status} — distribution-channels "
                "analysis requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape DistributionChannelArchitect's
    # offline / retail / store availability signal; feed them through so the
    # recomputed read matches the actual run instead of defaulting to
    # online-only distribution.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "consumer_hardware")
        or "consumer_hardware"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read
    # (which returns INSUFFICIENT_DATA for distribution).
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster distribution metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_distribution_channels(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/trust-barriers",
    response_model=TrustBarriersOut,
    summary=(
        "Trust barriers: market trust index, per-cluster objections, "
        "and highest-impact trust-building levers"
    ),
    responses=_JSON_200,
)
def get_trust_barriers(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrustBarriersOut:
    """
    Deterministic trust-barriers read from a completed run's
    ``TrustArchitect`` metrics:

      * population-weighted trust index (brand-deficit multiplier x
        social-proof coverage, penalized by security concern and trust
        decay), plus weighted security concern, recovery days, community
        signal, press lift, and free-trial substitute
      * per-cluster trust tiers (LOW / MODERATE / HIGH / CRITICAL)
      * per-cluster primary trust barrier (brand deficit, missing social
        proof, security concern, weak community signal, fast trust
        decay, slow recovery) with a market-level barrier distribution
      * ranked trust-building levers by the share of the covered market
        they touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Trust
    metrics are recomputed from the project's visible assumptions so
    brand / review signals from the brief shape the read. Works for all
    product types because TrustArchitect runs in every conductor stack.
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
                f"Simulation is {sim.status} — trust-barriers analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape TrustArchitect's brand /
    # review signals; feed them through so the recomputed read matches
    # the actual run instead of defaulting to neutral credibility.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster trust metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_trust_barriers(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/support-friction",
    response_model=SupportFrictionOut,
    summary=(
        "Support friction: post-purchase ticket burden, per-cluster "
        "friction drivers, and highest-impact support levers"
    ),
    responses=_JSON_200,
)
def get_support_friction(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SupportFrictionOut:
    """
    Deterministic support-friction read from a completed run's
    ``SupportFrictionArchitect`` metrics:

      * population-weighted friction index (ticket likelihood,
        self-serve resolution, response-time tolerance, bug tolerance,
        downtime sensitivity, documentation perception), plus estimated
        monthly support contacts and staffing per 10k users
      * per-cluster friction tiers (LOW / MODERATE / HIGH / CRITICAL)
      * per-cluster primary friction driver (ticket volume, self-serve
        gap, response tolerance, bug tolerance, downtime sensitivity,
        documentation gap) with a market-level driver distribution
      * ranked support levers by the share of the covered market they
        touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Support
    metrics are recomputed from the project's visible assumptions so
    complexity / documentation signals from the brief shape the read.
    Works for all product types because SupportFrictionArchitect runs
    in every conductor stack.
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
                f"Simulation is {sim.status} — support-friction analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape SupportFrictionArchitect's
    # complexity / documentation signals; feed them through so the
    # recomputed read matches the actual run instead of defaulting to
    # neutral complexity.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster support metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_support_friction(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/cultural-fit",
    response_model=CulturalFitOut,
    summary=(
        "Cultural fit: population-weighted adoption readiness, "
        "per-cluster cultural barriers, and localization levers"
    ),
    responses=_JSON_200,
)
def get_cultural_fit(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CulturalFitOut:
    """
    Deterministic cultural-fit read from a completed run's
    ``CulturalContextArchitect`` metrics:

      * population-weighted fit index (language accessibility, cultural
        alignment, family-gatekeeper pressure, religious-sensitivity
        risk, seasonal relevance, geo-target alignment)
      * per-cluster fit tiers (STRONG / MODERATE / WEAK / MISALIGNED)
      * per-cluster primary cultural barrier with a market-level
        barrier distribution
      * ranked localization levers by the share of the covered market
        they touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Cultural
    metrics are recomputed from the project's visible assumptions so
    language / festival / religious signals from the brief shape the
    read. Works for all product types because CulturalContextArchitect
    runs in every conductor stack.
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
                f"Simulation is {sim.status} — cultural-fit analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape CulturalContextArchitect's
    # language / festival / religious signals; feed them through so the
    # recomputed read matches the actual run instead of defaulting to
    # neutral signals.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster cultural metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_cultural_fit(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/ecosystem-compatibility",
    response_model=EcosystemCompatibilityOut,
    summary=(
        "Ecosystem compatibility: population-weighted compatibility "
        "index, per-cluster blockers, and integration levers"
    ),
    responses=_JSON_200,
)
def get_ecosystem_compatibility(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EcosystemCompatibilityOut:
    """
    Deterministic ecosystem-compatibility read from a completed run's
    ``EcosystemCompatibilityArchitect`` metrics:

      * population-weighted compatibility index (platform lock-in,
        smart-home requirement, subscription resentment, cloud privacy,
        voice expectation)
      * per-cluster compatibility tiers (OPEN / PARTIAL / TETHERED /
        LOCKED)
      * per-cluster primary compatibility blocker with a market-level
        blocker distribution
      * ranked ecosystem levers by the share of the covered market they
        touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Ecosystem
    metrics are recomputed from the project's visible assumptions so
    Matter / subscription / API signals from the brief shape the read.
    Supported for consumer_hardware, health_hardware, iot_hardware,
    smart_home and wearable product types.
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
                f"Simulation is {sim.status} — ecosystem-compatibility "
                "analysis requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape
    # EcosystemCompatibilityArchitect's Matter / subscription / API
    # signals; feed them through so the recomputed read matches the
    # actual run instead of defaulting to neutral signals.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster ecosystem metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_ecosystem_compatibility(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/setup-friction",
    response_model=SetupFrictionOut,
    summary=(
        "Setup & first-use friction: population-weighted "
        "setup-experience index, per-cluster setup blockers, and "
        "time-to-value levers"
    ),
    responses=_JSON_200,
)
def get_setup_friction(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SetupFrictionOut:
    """
    Deterministic setup-friction read from a completed run's
    ``SetupFirstUseArchitect`` metrics:

      * population-weighted setup-experience index (out-of-box
        completion, time to first meaningful use, companion-app
        install, account-creation abandonment, firmware-update,
        physical-assembly and pairing tolerances)
      * per-cluster setup tiers (SEAMLESS / ROUGH / SLOW / BLOCKED)
      * per-cluster primary setup blocker with a market-level blocker
        distribution
      * ranked time-to-value levers by the share of the covered market
        they touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Setup
    metrics are recomputed from the project's visible assumptions so
    companion-app / firmware / complexity signals from the brief shape
    the read; companion-app friction is only counted when the brief
    requires an app. Supported for consumer_hardware, health_hardware,
    iot_hardware, wearable and b2b_hardware product types.
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
                f"Simulation is {sim.status} — setup-friction analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape SetupFirstUseArchitect's
    # companion-app / firmware / complexity signals; feed them through
    # so the recomputed read matches the actual run instead of
    # defaulting to neutral signals.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]
    # Companion-app friction is only a real blocker when the brief
    # requires an app; the architect applies the same keyword signals.
    requires_companion_app = any(
        any(
            token in str(assumption.text or "").lower()
            for token in ("app required", "companion app", "mobile app setup")
        )
        for assumption in assumptions
    )

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster setup metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_setup_friction(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
        requires_companion_app=requires_companion_app,
    )


@router.get(
    "/{simulation_id}/retention-churn",
    response_model=RetentionChurnOut,
    summary=(
        "Retention & churn: market survival curve, per-cluster churn "
        "triggers, and highest-impact retention levers"
    ),
    responses=_JSON_200,
)
def get_retention_churn(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RetentionChurnOut:
    """
    Deterministic retention-churn read from a completed run's
    ``RetentionArchitect`` metrics:

      * population-weighted survival curve (day 1 / 7 / 30 / 90), habit
        loop duration, re-engagement probability, notification
        re-engagement, and pause-vs-cancel preference
      * per-cluster retention tiers (STICKY / STEADY / FADING /
        HIGH_CHURN)
      * per-cluster primary churn trigger (price sensitivity, onboarding
        friction, weak habit loop, feature drop-off) with a market-level
        trigger distribution and the biggest survival drop-off stage
      * ranked retention levers by the share of the covered market they
        touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Retention
    metrics are recomputed from the project's visible assumptions so
    onboarding / habit signals from the brief shape the read. Returns
    ``INSUFFICIENT_DATA`` for product types whose conductor stack does not
    model retention (consumer hardware, iot hardware, wearable, b2b
    hardware, smart home, ...).
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
                f"Simulation is {sim.status} — retention-churn analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape RetentionArchitect's habit /
    # use-frequency signals; feed them through so the recomputed read
    # matches the actual run instead of defaulting to neutral inputs.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster retention metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_retention_churn(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/market-timing",
    response_model=MarketTimingOut,
    summary=(
        "Market timing: launch-readiness index, per-cluster readiness "
        "tiers, and the gates blocking the covered market"
    ),
    responses=_JSON_200,
)
def get_market_timing(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarketTimingOut:
    """
    Deterministic market-timing read from a completed run's
    ``MarketTimingArchitect`` metrics:

      * population-weighted timing index (category awareness, problem
        urgency, budget-cycle alignment, technology adoption, switching
        comfort and category-education comfort, penalized by regulatory
        suppression)
      * per-cluster readiness tiers (READY_NOW / ALMOST_READY / EARLY /
        BLOCKED)
      * per-cluster primary readiness gate (regulation, category
        awareness, problem urgency, education cost, switching cost,
        adoption position, budget cycle) with a market-level gate
        distribution
      * a GO / CAUTIOUS / WAIT verdict, ranked launch opportunities from
        the ready part of the market, risk flags and actionable
        recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Timing
    metrics are recomputed from the project's visible assumptions so
    urgency / regulatory / seasonal signals from the brief shape the
    read. Works for all product types because MarketTimingArchitect runs
    in every conductor stack.
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
                f"Simulation is {sim.status} — market-timing analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape MarketTimingArchitect's
    # urgency / switching / regulatory / seasonal signals; feed them
    # through so the recomputed read matches the actual run instead of
    # defaulting to neutral inputs.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster timing metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_market_timing(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/competitive-moat",
    response_model=CompetitiveMoatOut,
    summary=(
        "Competitive moat: population-weighted defensibility index, "
        "per-cluster tiers, and the weakest moat lever"
    ),
    responses=_JSON_200,
)
def get_competitive_moat(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompetitiveMoatOut:
    """
    Deterministic competitive-moat read from a completed run's architect
    metrics:

      * population-weighted moat index built from five levers (feature
        parity, brand trust, pricing power, distribution reach and
        switching lock-in), with weights renormalized when an architect
        does not run for the product type
      * per-cluster tiers (MOAT_STRONG / MOAT_MODERATE / MOAT_WEAK)
      * each cluster's weakest defensibility lever with a market-level
        lever distribution
      * a STRONG / MODERATE / WEAK verdict, ranked protected and
        vulnerable clusters, risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Metrics
    are recomputed from the project's visible assumptions so
    competitor / trust / pricing signals from the brief shape the read.
    Works for all product types because CompetitiveDynamicsArchitect
    runs in every conductor stack.
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
                f"Simulation is {sim.status} — competitive-moat analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # The project's visible assumptions shape CompetitiveDynamicsArchitect's
    # competitor-type / differentiation signals, TrustArchitect's brand and
    # social-proof signals, and PricingArchitect's price ceiling; feed them
    # through so the recomputed read matches the actual run instead of
    # defaulting to neutral inputs.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster moat metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_competitive_moat(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/validation-roi",
    response_model=ValidationRoiOut,
    summary="Rank assumptions by expected value of validation (impact x uncertainty)",
    responses=_JSON_200,
)
def get_validation_roi(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationRoiOut:
    """
    Validation-ROI analysis from a completed simulation's results.

    Sensitivity tells a founder *which assumption matters most*; validation
    ROI adds the second axis — *how well is that assumption already backed by
    evidence?* Each assumption is scored ``sensitivity x uncertainty`` and
    ranked so the first experiment a founder runs de-risks the projection
    the most.

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
            detail=(
                f"Simulation is {sim.status} — validation-ROI analysis requires "
                "completed results."
            ),
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

    return build_validation_roi(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
    )


@router.get(
    "/{simulation_id}/validation-experiment-plan",
    response_model=ValidationExperimentPlanOut,
    summary="Turn validation-ROI rankings into a concrete, sequenced validation sprint",
    responses=_JSON_200,
)
def get_validation_experiment_plan(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationExperimentPlanOut:
    """
    Concrete validation experiment plan from a completed simulation's results.

    Composes the validation-ROI ranking (sensitivity x uncertainty) with a
    deterministic experiment selector: for every validate-first / high-value
    assumption the plan attaches a method, cost tier, duration, sample target,
    success threshold and go/no-go rule, sequenced by ROI so the first test a
    founder runs de-risks the projection the most.

    Pure post-hoc analysis — no Celery dispatch, no LLM calls.
    """
    roi = get_validation_roi(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )
    return build_validation_experiment_plan(roi)


@router.get(
    "/{simulation_id}/quality",
    response_model=SimulationQualityOut,
    summary="Simulation quality gate: trust score, cluster coverage and data-integrity checks",
    responses=_JSON_200,
)
def get_simulation_quality(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationQualityOut:
    """
    Deterministic quality gate over a completed simulation's results.

    Surfaces a 0..1 trust score with a PASS / REVIEW / FAIL verdict backed
    by per-check detail: headline-conversion bounds, agent-count sanity,
    cluster coverage against the 52-cluster registry, per-cluster rate
    bounds, headline-vs-weighted-blend consistency, funnel sanity, domain
    findings presence and NaN/Inf freedom. Founders see whether the numbers
    are safe to act on; developers get early warning of pipeline regressions.

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
            detail=(
                f"Simulation is {sim.status} — quality analysis requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    return build_simulation_quality(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=sim.results_json,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
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
    get_owned_project(db, current_user.id, project_id)

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


def _query_outcome_pairs(
    db: Session,
    project_id: int | None = None,
    owned_project_ids: list[int] | None = None,
) -> list[tuple[float | None, float | None]]:
    """Pull (predicted, actual) conversion pairs from recorded outcomes.

    Only pairs with both sides present are included — a missing prediction
    means the outcome can't teach the calibration layer anything.
    """
    q = db.query(
        Outcome.predicted_conversion_rate,
        Outcome.actual_conversion_rate,
    )
    if project_id is not None:
        q = q.filter(Outcome.project_id == project_id)
    else:
        q = q.filter(Outcome.project_id.in_(owned_project_ids or []))
    q = q.filter(
        Outcome.predicted_conversion_rate.isnot(None),
        Outcome.actual_conversion_rate.isnot(None),
    )
    q = q.order_by(Outcome.created_at.desc())
    rows = q.limit(200).all()
    return [(r[0], r[1]) for r in rows]


def _load_prediction_calibration_pairs(
    db: Session,
    project_id: int,
    owned_project_ids: list[int],
) -> tuple[list[tuple[float | None, float | None]], str]:
    """Choose the richest calibration set for a prediction-range read.

    Project-level outcomes are preferred because they share the same product
    context; when the project doesn't yet have enough pairs, the user's
    cross-project pool is used instead so early founders still get signal.
    """
    project_pairs = _query_outcome_pairs(db, project_id=project_id)
    if len(project_pairs) >= MIN_OUTCOMES_FOR_RANGE:
        return project_pairs, "project"
    user_pairs = _query_outcome_pairs(db, owned_project_ids=owned_project_ids)
    if len(user_pairs) >= MIN_OUTCOMES_FOR_RANGE:
        return user_pairs, "user"
    if project_pairs:
        return project_pairs, "project"
    return user_pairs, "user" if user_pairs else "none"


def _load_what_if_context(
    sim: Simulation,
    db: Session,
) -> tuple[dict, list[Assumption]]:
    """Load env params + visible assumptions needed to run what-if projections."""
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

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    return env_params, assumptions


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
        generated_at=datetime.now(UTC).isoformat(),
        tier_counts=tier_counts,
        cost_summary=cost_summary,
        clusters=clusters_out,
    )


_SIMULATION_ANOMALIES_CACHE_NAMESPACE = "simulation_anomalies"
_SIMULATION_ANOMALIES_CACHE_TTL_S = 60


@router.get(
    "/{simulation_id}/anomalies",
    response_model=SimulationAnomaliesOut,
    summary="Statistical anomalies and stage drop-off spikes for a simulation",
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_simulation_anomalies(
    simulation_id: int,
    outlier_z_threshold: float = Query(
        2.0, ge=1.0, le=5.0, description="Z-score threshold for cluster outliers"
    ),
    dropoff_spike_threshold: float = Query(
        0.75, ge=0.1, le=1.0, description="Stage drop-off rate cutoff"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationAnomaliesOut:
    """Detect statistical anomalies, funnel stage drop-off spikes, and cluster outliers.

    Analyzes a completed simulation's conversion funnel and cluster breakdown
    to flag bottlenecks, severe drop-offs, and unexpected metric deviations.
    """
    cache_params = {
        "simulation_id": simulation_id,
        "outlier_z_threshold": outlier_z_threshold,
        "dropoff_spike_threshold": dropoff_spike_threshold,
    }
    cached = cache_get_json(
        namespace=_SIMULATION_ANOMALIES_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
    )
    if cached is not None:
        return SimulationAnomaliesOut(**cached)

    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id == simulation_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not sim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation not found",
        )

    results_json = sim.results_json or {}
    payload = detect_simulation_anomalies(
        results_json=results_json,
        outlier_z_threshold=outlier_z_threshold,
        dropoff_spike_threshold=dropoff_spike_threshold,
    )

    cache_set_json(
        namespace=_SIMULATION_ANOMALIES_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_SIMULATION_ANOMALIES_CACHE_TTL_S,
    )
    return SimulationAnomaliesOut(**payload)


_SIMULATION_SENSITIVITY_CACHE_NAMESPACE = "simulation_sensitivity_matrix"
_SIMULATION_SENSITIVITY_CACHE_TTL_S = 60


@router.get(
    "/{simulation_id}/sensitivity-matrix",
    response_model=SimulationSensitivityMatrixOut,
    summary="Trait sensitivity and elasticity matrix for a simulation",
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_simulation_sensitivity_matrix(
    simulation_id: int,
    delta_step: float = Query(
        0.1, ge=0.01, le=0.5, description="Perturbation step for elasticity computation"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationSensitivityMatrixOut:
    """Compute sensitivity and elasticity matrix across cluster traits.

    Evaluates how variations in consumer cluster traits (price sensitivity, trust,
    digital literacy, etc.) impact final conversion rates.
    """
    cache_params = {
        "simulation_id": simulation_id,
        "delta_step": delta_step,
    }
    cached = cache_get_json(
        namespace=_SIMULATION_SENSITIVITY_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
    )
    if cached is not None:
        return SimulationSensitivityMatrixOut(**cached)

    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id == simulation_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not sim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation not found",
        )

    results_json = sim.results_json or {}
    payload = compute_simulation_sensitivity_matrix(
        results_json=results_json,
        delta_step=delta_step,
    )

    cache_set_json(
        namespace=_SIMULATION_SENSITIVITY_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_SIMULATION_SENSITIVITY_CACHE_TTL_S,
    )
    return SimulationSensitivityMatrixOut(**payload)


@router.get(
    "/{simulation_id}/market-sizing",
    response_model=MarketSizingOut,
    summary="TAM/SAM/SOM and annual revenue projection for a simulation",
    responses=_JSON_200,
)
def get_market_sizing(
    simulation_id: int,
    market_size: int = Query(
        DEFAULT_MARKET_SIZE,
        ge=MIN_MARKET_SIZE,
        le=MAX_MARKET_SIZE,
        description="Total addressable market (people) to reason about",
    ),
    target_market_fraction: float = Query(
        DEFAULT_TARGET_MARKET_FRACTION,
        ge=MIN_TARGET_MARKET_FRACTION,
        le=MAX_TARGET_MARKET_FRACTION,
        description="Share of the reachable market in the launch segment",
    ),
    average_order_value: float = Query(
        DEFAULT_AVERAGE_ORDER_VALUE,
        ge=0,
        description="Revenue per converted customer (set 0 to skip revenue)",
    ),
    purchase_frequency_per_year: float = Query(
        DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
        ge=0,
        description="Purchases per customer per year",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarketSizingOut:
    """Project TAM / SAM / SOM + annual revenue from completed results.

    Builds a founder-facing market-sizing digest from the run's
    weighted conversion and cluster breakdown: the obtainable
    market (SOM) is the reachable share of the target market
    times the simulation's conversion, and annual revenue is
    SOM x AOV x purchase frequency. Pure analytics — no Celery,
    no LLM.
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
                f"Simulation is {sim.status} — market sizing requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    registry = {
        cid: {
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cid, cluster in _clusters_map.items()
    }

    payload = build_market_sizing(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        market_size=market_size,
        target_market_fraction=target_market_fraction,
        average_order_value=average_order_value,
        purchase_frequency_per_year=purchase_frequency_per_year,
        cluster_registry=registry,
        signal_quality=(
            float(sim.signal_quality)
            if sim.signal_quality is not None
            else None
        ),
    )
    return MarketSizingOut(**payload)


@router.get(
    "/{simulation_id}/after-sales",
    response_model=AfterSalesOut,
    summary=(
        "After-sales lifecycle: population-weighted post-purchase "
        "health index, per-cluster after-sales risks, and levers"
    ),
    responses=_JSON_200,
)
def get_after_sales(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AfterSalesOut:
    """
    Deterministic after-sales lifecycle read from a completed run's
    ``AftersalesLifecycleArchitect`` metrics:

      * population-weighted after-sales index (support contact,
        repeat-purchase loyalty, warranty claims, negative-review risk,
        spare-parts concern, expected lifespan and accessory attach)
      * per-cluster after-sales tiers (STRONG / OK / FRAGILE / AT_RISK)
      * per-cluster primary after-sales risk with a market-level risk
        distribution
      * ranked post-purchase levers by the share of the covered market
        they touch, plus risk flags and actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. The
    per-cluster metrics are recomputed deterministically from the
    project's environment and assumptions so the read matches the run's
    hardware stack. Supported for consumer_hardware, health_hardware,
    iot_hardware, wearable and b2b_hardware product types.
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
                f"Simulation is {sim.status} — after-sales analysis "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    # Feed the project's visible assumptions through so the recomputed
    # run matches the actual simulation instead of defaulting to
    # neutral signals.
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    # Keep the read consistent with the stack actually recomputed below:
    # an unknown persisted value falls back to the SAAS stack and read.
    product_type_name = product_type.value

    # Recompute the deterministic architect stack for this product type so
    # per-cluster after-sales metrics are available even though regular
    # simulation runs only persist aggregate results. No DB writes are
    # performed (no session passed to run()).
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    raw_signal_quality = sim.signal_quality
    clean_signal_quality: float | None = None
    if raw_signal_quality is not None:
        try:
            clean_signal_quality = float(raw_signal_quality)
        except (TypeError, ValueError, OverflowError):
            clean_signal_quality = None

    return build_after_sales_read(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=clean_signal_quality,
        visible_assumption_count=len(assumptions),
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/launch-checklist",
    response_model=LaunchChecklistOut,
    summary=(
        "Launch readiness checklist: deterministic score over persisted "
        "results, signal quality, coverage and assumptions"
    ),
    responses=_JSON_200,
)
def get_launch_checklist(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LaunchChecklistOut:
    """
    Deterministic launch-readiness checklist from a completed run.

    Surfaces a 0..1 ``readiness_score`` with a READY / NEEDS_WORK /
    NOT_READY verdict over the run's persisted payload: results present,
    headline conversion bounds, cluster coverage, signal quality, visible
    assumptions, funnel sanity and domain findings. Pure post-hoc
    analytics — no Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — launch checklist requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_launch_checklist(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        visible_assumption_count=len(assumptions),
        product_type=product_type_name,
        cluster_registry=registry,
    )


@router.get(
    "/{simulation_id}/launch-checklist/export",
    response_class=StreamingResponse,
    summary=(
        "Export the launch readiness checklist as CSV, JSON, or Markdown"
    ),
)
def export_launch_checklist(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a multi-section "
            "spreadsheet; ``json`` returns the raw checklist payload; "
            "``md`` returns a founder-facing Markdown brief. "
            "Unsupported values return 422."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the launch readiness checklist for a completed simulation."""
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
                f"Simulation is {sim.status} — launch checklist export "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    checklist = get_launch_checklist(simulation_id, db, current_user)

    project = (
        db.query(Project)
        .filter(Project.id == sim.project_id)
        .first()
    )
    project_name = project.title if project else None

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": sim.project_id,
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported export format: {format}. "
                "Choose csv, json, or md."
            ),
        )
    if fmt == "json":
        body = launch_checklist_to_json(checklist, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="launch-checklist-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    if fmt == "md":
        md_text = launch_checklist_to_markdown(
            checklist,
            simulation_id=simulation_id,
            project_id=sim.project_id,
            project_name=project_name,
            metadata=metadata,
        )
        body = md_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="launch-checklist-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = launch_checklist_to_csv(checklist, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="launch-checklist-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/founder-brief",
    response_model=FounderBriefOut,
    summary=(
        "Founder brief: one digest of trust score, launch readiness, "
        "conversion, market sizing and top recommendations"
    ),
    responses=_JSON_200,
)
def get_founder_brief(
    simulation_id: int,
    market_size: int = Query(
        DEFAULT_MARKET_SIZE,
        ge=MIN_MARKET_SIZE,
        le=MAX_MARKET_SIZE,
        description="Total addressable market (people) to reason about",
    ),
    target_market_fraction: float = Query(
        DEFAULT_TARGET_MARKET_FRACTION,
        ge=MIN_TARGET_MARKET_FRACTION,
        le=MAX_TARGET_MARKET_FRACTION,
        description="Share of the reachable market in the launch segment",
    ),
    average_order_value: float = Query(
        DEFAULT_AVERAGE_ORDER_VALUE,
        ge=0,
        description="Revenue per converted customer (set 0 to skip revenue)",
    ),
    purchase_frequency_per_year: float = Query(
        DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
        ge=0,
        description="Purchases per customer per year",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FounderBriefOut:
    """
    Founder-facing digest for a completed simulation.

    Combines the deterministic quality gate, launch checklist and
    market-sizing projection into one read: headline conversion, trust
    score, readiness score, TAM/SAM/SOM, annual revenue and the top
    recommendations across the underlying reads. Pure post-hoc
    analytics — no Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — founder brief requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_founder_brief(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        visible_assumption_count=len(assumptions),
        product_type=product_type_name,
        cluster_registry=registry,
        market_size=market_size,
        target_market_fraction=target_market_fraction,
        average_order_value=average_order_value,
        purchase_frequency_per_year=purchase_frequency_per_year,
    )


@router.get(
    "/{simulation_id}/fix-leverage",
    response_model=FixLeverageOut,
    summary=(
        "Fix-leverage projection: what conversion could look like if the "
        "top domain findings were fixed"
    ),
    responses=_JSON_200,
)
def get_fix_leverage(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FixLeverageOut:
    """
    Deterministic conversion-update projection from a completed run.

    Maps the persisted domain findings to the forward funnel transitions
    they would improve and returns a capped projected conversion alongside
    the baseline, absolute lift, and relative lift. Pure post-hoc analytics
    — no Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — fix-leverage projection "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    return build_fix_leverage(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=(
            float(sim.signal_quality) if sim.signal_quality is not None else None
        ),
    )


@router.get(
    "/{simulation_id}/founder-action-plan",
    response_model=FounderActionPlanOut,
    summary=(
        "Founder action plan: ranked, effort-weighted next actions with "
        "quick-win prioritisation"
    ),
    responses=_JSON_200,
)
def get_founder_action_plan(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FounderActionPlanOut:
    """
    Deterministic founder action plan from a completed run.

    Re-uses the persisted domain findings and funnel metrics to produce a
    ranked action list sorted by quick-win score (conversion impact per
    unit of implementation effort). Pure post-hoc analytics — no Celery,
    no LLM, no DB writes.
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
                f"Simulation is {sim.status} — founder action plan requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    return build_founder_action_plan(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        product_type=product_type_name,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
    )


@router.get(
    "/{simulation_id}/founder-action-plan/export",
    response_class=StreamingResponse,
    summary=(
        "Export the founder action plan as CSV (or JSON with ?format=json)"
    ),
    # Same DB read cost as the JSON founder-action-plan endpoint; cap
    # polling so a dashboard loop can't drive repeated reads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_founder_action_plan(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "founder-action-plan payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a simulation's founder action plan.

    Default ``format=csv`` renders the summary and the ranked actions as a
    multi-section spreadsheet. ``format=json`` returns the raw payload for
    machine consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    payload = get_founder_action_plan(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "json":
        body = founder_action_plan_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="founder-action-plan.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = founder_action_plan_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="founder-action-plan.csv"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{simulation_id}/assumption-postmortem",
    response_model=AssumptionPostmortemOut,
    summary=(
        "Assumption postmortem: which assumptions did launch outcomes "
        "invalidate or validate?"
    ),
    responses=_JSON_200,
)
def get_assumption_postmortem(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionPostmortemOut:
    """
    Assumption-level learning digest for a completed simulation.

    Compares the run's predicted conversion against the recorded founder
    outcome and scores each project assumption by sensitivity × conversion
    gap, so the dashboard can show which assumptions reality most likely
    invalidated (or validated) after launch. Pure post-hoc analytics — no
    Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — assumption postmortem requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    outcome = (
        db.query(Outcome)
        .filter(
            Outcome.simulation_id == sim.id,
            Outcome.actual_conversion_rate.isnot(None),
        )
        .order_by(Outcome.created_at.desc())
        .first()
    )
    if outcome is None:
        # Allow the project-level latest outcome as a fallback so founders
        # who recorded outcomes before simulation linkage still get a read.
        outcome = (
            db.query(Outcome)
            .filter(
                Outcome.project_id == sim.project_id,
                Outcome.actual_conversion_rate.isnot(None),
            )
            .order_by(Outcome.created_at.desc())
            .first()
        )

    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == sim.project_id,
            Assumption.is_hidden.is_(False),
        )
        .all()
    )

    outcome_dict: dict[str, object] | None = None
    if outcome is not None:
        outcome_dict = {
            "simulation_id": outcome.simulation_id,
            "actual_conversion_rate": outcome.actual_conversion_rate,
        }

    assumption_dicts = [
        {
            "id": a.id,
            "text": a.text,
            "category": a.category,
            "sensitivity": a.sensitivity,
            "impact_score": a.impact_score,
        }
        for a in assumptions
    ]

    return build_assumption_postmortem(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        assumptions=assumption_dicts,
        outcome=outcome_dict,
    )


@router.get(
    "/{simulation_id}/prediction-range",
    response_model=PredictionRangeOut,
    summary=(
        "Accuracy-adjusted prediction range: the realistic band around "
        "a run's predicted conversion rate"
    ),
    responses=_JSON_200,
)
def get_prediction_range(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PredictionRangeOut:
    """
    Prediction-range digest for a completed simulation.

    Blends the run's predicted conversion rate with the historical
    (predicted, actual) outcome pairs from this project (or the founder's
    cross-project pool when the project is still young) and emits a realistic
    low/high band plus a calibration label. Pure post-hoc analytics — no
    Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — prediction range requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    predicted = extract_predicted_conversion(sim.results_json)

    owned_project_ids = [
        p.id for p in db.query(Project).filter(Project.user_id == current_user.id).all()
    ]
    pairs, source = _load_prediction_calibration_pairs(
        db,
        sim.project_id,
        owned_project_ids,
    )

    return PredictionRangeOut(
        **build_prediction_range(
            predicted_conversion_rate=predicted,
            pairs=pairs,
            simulation_id=sim.id,
            project_id=sim.project_id,
            calibration_source=source,
        )
    )


@router.get(
    "/{simulation_id}/channel-attribution",
    response_model=ChannelAttributionOut,
    summary=(
        "Channel attribution: market channel ranking, lowest-CAC "
        "channel, and recommended budget mix"
    ),
    responses=_JSON_200,
)
def get_channel_attribution(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelAttributionOut:
    """
    Deterministic acquisition-channel read from a completed run.

    Reuses the channel-attribution engine that powers generated-UI runs
    and exposes it directly against a regular simulation: per-cluster
    channel scores, the population-weighted market channel ranking, the
    lowest-CAC channel, and a recommended budget mix for early spend.
    Pure post-hoc analytics — no Celery, no LLM, no DB writes.
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
                f"Simulation is {sim.status} — channel attribution "
                "requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    return build_channel_attribution(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/sustainability-positioning",
    response_model=SustainabilityPositioningOut,
    summary=(
        "Sustainability positioning: ESG claim reach, population-weighted "
        "conversion lift, per-cluster response tiers, and risk flags"
    ),
    responses=_JSON_200,
)
def get_sustainability_positioning(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SustainabilityPositioningOut:
    """
    Deterministic sustainability-positioning read from a completed run's
    ``SustainabilityArchitect`` metrics:

      * whether the brief makes environmental / ethical-sourcing claims
        and whether those claims are evidence-backed
      * population-weighted ESG affinity, green premium tolerance,
        conversion lift, and premium friction
      * the share of the covered market whose conversion model responds
        to sustainability positioning
      * per-cluster response tiers (HIGH / MODERATE / LOW / NO_SIGNAL)
      * the highest-impact clusters to lead with, plus market-level
        greenwashing, premium-friction and narrow-reach flags and
        actionable recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Metrics
    are recomputed from the project's visible assumptions so
    eco / ethical / evidence signals from the brief shape the read. Works
    for all product types because SustainabilityArchitect runs in every
    conductor stack.
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
                f"Simulation is {sim.status} — sustainability-positioning "
                "analysis requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
            "sustainability_weight": 1.0,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    raw_signal_quality = sim.signal_quality
    signal_quality: float | None = None
    if raw_signal_quality is not None:
        try:
            signal_quality = float(raw_signal_quality)
        except (TypeError, ValueError, OverflowError):
            signal_quality = None

    return build_sustainability_positioning(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/assumption-cascade",
    response_model=AssumptionCascadeOut,
    summary=(
        "Assumption cascade: population-weighted risk index, per-cluster "
        "risk tiers, compound-failure and blind-spot blockers"
    ),
    responses=_JSON_200,
)
def get_assumption_cascade(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionCascadeOut:
    """
    Deterministic assumption-cascade read from a completed run's
    ``AssumptionCascadeArchitect`` metrics:

      * population-weighted cascade risk index (0..1, higher = worse)
      * per-cluster risk tiers (LOW / ELEVATED / HIGH / CRITICAL)
      * dominant blockers (existential cascade, compound dual-failure,
        validation blind spots, sensitive segments)
      * top-risk clusters for validation focus
      * STABLE / WATCH / RISKY / HIGH_RISK verdict and actionable
        recommendations

    Pure post-hoc analytics — no Celery, no LLM, no DB writes. Metrics
    are recomputed from the project's visible assumptions so the
    project's critical / high-sensitivity assumptions shape the read.
    ``AssumptionCascadeArchitect`` runs in every conductor stack, so
    the read is supported for all product types.
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
                f"Simulation is {sim.status} — assumption-cascade "
                "analysis requires completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.id == sim.environment_id)
        .first()
    )
    aov = 999.0
    price_sensitivity = 0.5
    market_maturity = 0.3
    if environment:
        aov = float(environment.average_order_value or 999.0)
        price_sensitivity = float(environment.price_sensitivity or 0.5)
        market_maturity = float(environment.market_maturity or 0.3)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == sim.project_id, Assumption.is_hidden.is_(False))
        .all()
    )
    assumption_dicts = [
        {
            "text": assumption.text,
            "sensitivity": str(assumption.sensitivity or "MEDIUM"),
            "impact_score": float(
                assumption.impact_score
                if assumption.impact_score is not None
                else 5.0
            ),
        }
        for assumption in assumptions
    ]

    product_type_name = str(
        (sim.results_json or {}).get("product_type_detected", "saas") or "saas"
    )
    try:
        product_type = ProductType(product_type_name)
    except ValueError:
        product_type = ProductType.SAAS
    product_type_name = product_type.value

    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": aov,
            "price_sensitivity": price_sensitivity,
            "market_maturity": market_maturity,
        },
        assumptions=assumption_dicts,
        product_type=product_type,
    )
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in _clusters_map.values()
    ]

    raw_signal_quality = sim.signal_quality
    signal_quality: float | None = None
    if raw_signal_quality is not None:
        try:
            signal_quality = float(raw_signal_quality)
        except (TypeError, ValueError, OverflowError):
            signal_quality = None

    return build_assumption_cascade(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        visible_assumption_count=len(assumptions),
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )


@router.get(
    "/{simulation_id}/export",
    summary=(
        "Per-simulation spreadsheet export — key metrics plus "
        "one row per cluster (CSV by default, JSON with "
        "?format=json)"
    ),
    response_class=StreamingResponse,
)
def get_simulation_export(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the "
            "raw export payload. Anything other than ``json`` "
            "falls back to ``csv``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a single completed simulation.

    Default ``format=csv`` returns a flat table with simulation-level
    metadata on every row plus each cluster's population weight and
    conversion rate. ``format=json`` returns the same data as a JSON
    document so machine consumers can avoid CSV parsing.
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
                f"Simulation is {sim.status} — export requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    product_type = str(
        (sim.results_json or {}).get("product_type_detected", "saas")
        or "saas"
    ).lower()
    cluster_names = {
        cluster.cluster_id: cluster.name
        for cluster in _registry.all_clusters()
    }
    cluster_weights = {
        cluster.cluster_id: float(cluster.population_weight or 0.0)
        for cluster in _registry.all_clusters()
    }

    raw_signal_quality = sim.signal_quality
    clean_signal_quality: float | None = None
    if raw_signal_quality is not None:
        try:
            clean_signal_quality = float(raw_signal_quality)
        except (TypeError, ValueError, OverflowError):
            clean_signal_quality = None

    export = build_simulation_export(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        product_type=product_type,
        signal_quality=clean_signal_quality,
        cluster_names=cluster_names,
        cluster_weights=cluster_weights,
        created_at=sim.created_at,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {"metadata": metadata, "simulation": export},
            default=str,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="simulation-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = simulation_to_csv(export, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="simulation-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/findings/export",
    summary=(
        "Export one simulation's domain findings as CSV, JSON, or a "
        "founder-facing Markdown brief"
    ),
    response_class=StreamingResponse,
)
def get_findings_export(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "findings list; ``md`` returns a Markdown founder brief."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a single simulation's domain findings."""
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
                f"Simulation is {sim.status} — findings export requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    findings = extract_findings(sim.results_json)
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "metadata": metadata,
                "simulation_id": simulation_id,
                "project_id": sim.project_id,
                "findings": findings,
            },
            default=str,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="findings-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    if fmt == "md":
        md_text = findings_to_markdown(
            findings,
            simulation_id=simulation_id,
            project_id=sim.project_id,
            primary_failure_domain=(
                sim.results_json.get("primary_failure_domain")
                if isinstance(sim.results_json, dict)
                else None
            ),
            metadata=metadata,
        )
        body = md_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="findings-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = findings_to_csv(
        findings,
        metadata=metadata,
        simulation_id=simulation_id,
        project_id=sim.project_id,
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="findings-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )
