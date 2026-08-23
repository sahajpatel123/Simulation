from __future__ import annotations

import copy
import json
import logging
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
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
from app.core.metrics import metrics
from app.core.progress_bridge import progress_bridge
from app.core.rate_limiter import rate_limit
from app.core.redis_client import get_redis_client
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
from app.core.tier_enforcement import enforce_simulation_limit
from app.core.websocket import sync_broadcast
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
from app.schemas.architect_stack import ArchitectStackRegistryOut
from app.schemas.assumption_cascade import AssumptionCascadeOut
from app.schemas.assumption_postmortem import AssumptionPostmortemOut
from app.schemas.buyer_personas import BuyerPersonasOut
from app.schemas.calibration_transparency import CalibrationTransparencyOut
from app.schemas.channel_attribution import ChannelAttributionOut
from app.schemas.cluster_opportunity import ClusterOpportunityMatrixOut
from app.schemas.cohort_retention import CohortRetentionOut
from app.schemas.competitive_moat import CompetitiveMoatOut
from app.schemas.cultural_fit import CulturalFitOut
from app.schemas.distribution_channels import DistributionChannelsOut
from app.schemas.ecosystem_compatibility import EcosystemCompatibilityOut
from app.schemas.feature_prioritization import FeaturePrioritizationOut
from app.schemas.first_customers import FirstCustomersOut
from app.schemas.fix_leverage import FixLeverageOut
from app.schemas.founder_action_plan import FounderActionPlanOut
from app.schemas.founder_brief import FounderBriefOut
from app.schemas.funnel_diagnosis import FunnelDiagnosisOut
from app.schemas.investor_readiness import InvestorReadinessOut
from app.schemas.journey_analytics import JourneyAnalyticsOut
from app.schemas.journey_benchmark import (
    JourneyBenchmarkOut,
    JourneyCategoryBenchmarkOut,
)
from app.schemas.journey_trend import JourneyTrendOut
from app.schemas.launch_checklist import LaunchChecklistOut
from app.schemas.market_concentration import MarketConcentrationOut
from app.schemas.market_sizing import MarketSizingOut
from app.schemas.market_timing import MarketTimingOut
from app.schemas.portfolio_launch_priority import PortfolioLaunchPriorityOut
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
    IdenticalInputRunOut,
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
    SimulationCancelOut,
    SimulationCreate,
    SimulationReproducibilityOut,
    SimulationResultOut,
    SimulationSensitivityMatrixOut,
    SimulationStatusOut,
)
from app.schemas.simulation_compare import SimulationRunDiffOut
from app.schemas.simulation_comparison import (
    SimulationCompareRequest,
    SimulationComparisonOut,
)
from app.schemas.simulation_quality import SimulationQualityOut
from app.schemas.support_friction import SupportFrictionOut
from app.schemas.sustainability_positioning import SustainabilityPositioningOut
from app.schemas.trust_barriers import TrustBarriersOut
from app.schemas.unit_economics import UnitEconomicsOut
from app.schemas.validation_experiment import (
    COST_TIER_LITERAL,
    ValidationExperimentPlanOut,
)
from app.schemas.validation_roi import ValidationRoiOut
from app.schemas.validation_sprint import ValidationSprintScheduleOut
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
from app.simulation.architect_stack import build_architect_stack_registry
from app.simulation.assumption_cascade_read import build_assumption_cascade
from app.simulation.assumption_postmortem import build_assumption_postmortem
from app.simulation.buyer_personas import build_buyer_personas
from app.simulation.calibration_health import (
    build_calibration_health,
)
from app.simulation.calibration_health_export import calibration_health_to_csv
from app.simulation.calibration_transparency import (
    DEFAULT_CORRECTIONS_LIMIT,
    MAX_CORRECTIONS_LIMIT,
    build_calibration_transparency,
    coerce_recorded_applied_corrections,
)
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
from app.simulation.cluster_run_summary_export import (
    build_cluster_run_summary_export,
    cluster_run_summary_to_csv,
    cluster_run_summary_to_json,
)
from app.simulation.cluster_trend import (
    build_cluster_trend,
)
from app.simulation.cluster_trend import (
    normalise_bin as normalise_trend_bin,
)
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.cohort_retention_export import (
    FORMAT_VERSION as cohort_retention_export_FORMAT_VERSION,
)
from app.simulation.cohort_retention_export import (
    cohort_retention_to_csv,
    cohort_retention_to_json,
    cohort_retention_to_markdown,
)
from app.simulation.competitive_moat import build_competitive_moat
from app.simulation.conductor import ARCHITECT_STACKS, Conductor
from app.simulation.coverage_gaps import build_coverage_gaps
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
    findings_count_to_csv,
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
from app.simulation.first_customers import (
    DEFAULT_MONTHLY_VISITORS,
    MAX_MONTHLY_VISITORS,
    MIN_MONTHLY_VISITORS,
    build_first_customers,
)
from app.simulation.fix_leverage import build_fix_leverage
from app.simulation.founder_action_plan_export import (
    founder_action_plan_to_csv,
    founder_action_plan_to_json,
)
from app.simulation.founder_brief import build_founder_brief
from app.simulation.go_no_go import build_go_no_go
from app.simulation.investor_readiness import build_investor_readiness
from app.simulation.journey_analytics import (
    build_journey_analytics,
    deserialise_per_cluster_matrices,
    summarise_journey_matrices,
)
from app.simulation.journey_analytics_export import (
    FORMAT_VERSION as JOURNEY_ANALYTICS_FORMAT_VERSION,
)
from app.simulation.journey_analytics_export import (
    journey_analytics_to_csv,
    journey_analytics_to_json,
)
from app.simulation.journey_benchmark import build_journey_benchmark
from app.simulation.journey_benchmark_export import (
    FORMAT_VERSION as JOURNEY_BENCHMARK_FORMAT_VERSION,
)
from app.simulation.journey_benchmark_export import (
    journey_benchmark_to_csv,
    journey_benchmark_to_json,
)
from app.simulation.journey_trend import build_journey_trend
from app.simulation.journey_trend_export import (
    FORMAT_VERSION as JOURNEY_TREND_FORMAT_VERSION,
)
from app.simulation.journey_trend_export import (
    journey_trend_to_csv,
    journey_trend_to_json,
)
from app.simulation.launch_checklist import build_launch_checklist
from app.simulation.launch_checklist_export import (
    launch_checklist_to_csv,
    launch_checklist_to_json,
    launch_checklist_to_markdown,
)
from app.simulation.market_concentration import build_market_concentration
from app.simulation.market_concentration_export import (
    market_concentration_to_csv,
    market_concentration_to_json,
)
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
from app.simulation.portfolio_launch_priority import (
    build_portfolio_launch_priority,
)
from app.simulation.portfolio_launch_priority_export import (
    portfolio_launch_priority_to_csv,
)
from app.simulation.portfolio_narrative import (
    build_portfolio_narrative,
)
from app.simulation.prediction_range import (
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range,
    extract_predicted_conversion,
)
from app.simulation.premortem_digest import build_premortem_digest
from app.simulation.pricing_optimization import build_pricing_optimization
from app.simulation.pricing_optimization_export import (
    FORMAT_VERSION as PRICING_OPTIMIZATION_FORMAT_VERSION,
)
from app.simulation.pricing_optimization_export import (
    pricing_optimization_to_csv,
    pricing_optimization_to_json,
    pricing_optimization_to_markdown,
)
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
from app.simulation.simulation_compare import (
    build_simulation_comparison as build_run_diff,
)
from app.simulation.simulation_export import (
    build_simulation_export,
    simulation_to_csv,
)
from app.simulation.stress_scenarios_export import (
    FORMAT_VERSION as stress_scenarios_export_FORMAT_VERSION,
)
from app.simulation.stress_scenarios_export import (
    stress_scenarios_to_csv,
    stress_scenarios_to_json,
    stress_scenarios_to_markdown,
)
from app.simulation.support_friction import build_support_friction
from app.simulation.sustainability_positioning import (
    build_sustainability_positioning,
)
from app.simulation.trust_barriers import build_trust_barriers
from app.simulation.unit_economics import build_unit_economics
from app.simulation.unit_economics_export import unit_economics_to_csv
from app.simulation.validation_experiment_plan_export import (
    validation_experiment_plan_to_csv,
    validation_experiment_plan_to_json,
    validation_experiment_plan_to_markdown,
)
from app.simulation.validation_experiment_planner import build_validation_experiment_plan
from app.simulation.validation_roi import build_validation_roi
from app.simulation.validation_sprint_scheduler import schedule_validation_sprint
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
from app.simulation.reproducibility import (
    inputs_are_identical,
    stable_result_fingerprint,
)
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
from app.tasks.simulation_tasks import (
    _enqueue_simulation_webhooks,
    build_environment_snapshot,
    resolve_simulation_seed,
    run_full_simulation,
)
from app.worker import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

_registry = ClusterRegistry()
_clusters_map = {c.cluster_id: c for c in _registry.all_clusters()}

# Every user-scoped cache namespace that derives from simulation state.
# Both enqueue and cancel bust the same set so stale dashboard widgets
# can't outlive the lifecycle transition they describe.
_SIMULATION_CACHE_NAMESPACES: tuple[str, ...] = (
    _PORTFOLIO_NARRATIVE_CACHE_NAMESPACE,
    _NEXT_ACTION_CACHE_NAMESPACE,
    _ACTIVITY_FEED_CACHE_NAMESPACE,
    _USER_DASHBOARD_CACHE_NAMESPACE,
    _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
    _PROJECT_HEALTH_CACHE_NAMESPACE,
    _USER_NOTIFICATIONS_CACHE_NAMESPACE,
    _ADOPTION_MILESTONES_CACHE_NAMESPACE,
    _PROJECT_EXPORT_CACHE_NAMESPACE,
    _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
    _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
    _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
    _USER_QUICK_STATS_CACHE_NAMESPACE,
    _STATUS_BANNER_CACHE_NAMESPACE,
    _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
    _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
    _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
    _USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
    _USER_DECISION_VELOCITY_CACHE_NAMESPACE,
    _USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
    _USER_DECISION_RATE_CACHE_NAMESPACE,
    _USER_OUTCOME_RATE_CACHE_NAMESPACE,
    _USER_INSIGHTS_CACHE_NAMESPACE,
    _USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
    _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
    _USER_SIM_FAILURE_RATE_CACHE_NAMESPACE,
    _USER_RUNS_PER_WEEK_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
    _USER_OLDEST_OPEN_ITEM_CACHE_NAMESPACE,
    _STALE_CHECK_CACHE_NAMESPACE,
    _LATEST_SNAPSHOT_CACHE_NAMESPACE,
)


def _invalidate_simulation_caches(user_id: int) -> None:
    """Bust every user-scoped cache that derives from simulation state."""
    for namespace in _SIMULATION_CACHE_NAMESPACES:
        cache_invalidate(namespace=namespace, user_id=user_id)


def _stored_or_computed_fingerprint(sim: Simulation) -> str | None:
    """Return a run's reproducibility fingerprint.

    Prefers the fingerprint persisted by the worker at completion; legacy
    completed runs fall back to computing it from the stored results
    payload with the same canonical algorithm.
    """
    if sim.results_fingerprint:
        return sim.results_fingerprint
    if sim.status == "COMPLETED":
        return stable_result_fingerprint(sim.results_json)
    return None


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
        seed=payload.seed,
        env_snapshot_json=build_environment_snapshot(
            environment, payload.consumer_volume
        ),
    )
    db.add(sim)
    db.commit()
    db.refresh(sim)

    task = run_full_simulation.delay(sim.id)
    sim.task_id = task.id
    db.commit()
    db.refresh(sim)

    logger.info(f"[API] Simulation enqueued - simulation_id={sim.id} task_id={task.id}")

    # Bust every user-scoped cache that derives from simulation state so
    # the next GETs reflect the new sim rather than waiting out the TTL.
    _invalidate_simulation_caches(current_user.id)

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


@router.post(
    "/{simulation_id}/rerun",
    response_model=SimulationStatusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Re-run a completed simulation with identical inputs and RNG seed",
    responses={
        201: {"description": "Identical re-run enqueued"},
        400: {"description": "Project environment is no longer configured"},
        404: {"description": "Simulation not found"},
        409: {"description": "Simulation is not completed or a run is already in flight"},
    },
    # Mutating lifecycle endpoint backed by Celery — 10/min/IP is plenty
    # for a human verifying reproducibility and bounds accidental loops.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def rerun_simulation(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationStatusOut:
    """Queue an exact replay of a completed simulation.

    The clone reuses the source run's frozen environment snapshot and the
    same RNG seed, so a rerun whose result differs from the source is
    evidence of non-seed factors (input edits, calibration drift,
    infrastructure) rather than sampling noise.
    """
    source = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == current_user.id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if source.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {source.status} — rerun requires completed results.",
        )

    # Lock the PROJECT row — not just the source simulation — so
    # concurrent reruns of any simulation in this project (and concurrent
    # create/rerun pairs) serialise on the same critical section as
    # create_simulation. Without the project lock, two reruns of different
    # completed sims could both observe an empty in-flight set, both
    # insert QUEUED rows, and drain two tier-quota slots for one click.
    # The row lock is held until this transaction commits.
    db.query(Project).filter(Project.id == source.project_id).with_for_update().one()

    try:
        enforce_simulation_limit(current_user, db)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "[API] Tier quota pre-check failed for user_id=%s; deferring to worker",
            current_user.id,
        )

    running = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == source.project_id,
            Simulation.status.in_(["QUEUED", "RUNNING"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation {running.id} is already {running.status} for this project.",
        )

    environment = (
        db.query(Environment)
        .filter(Environment.project_id == source.project_id)
        .first()
    )
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /api/v1/projects/{id}/environments first.",
        )

    env_snapshot = (
        copy.deepcopy(source.env_snapshot_json)
        if isinstance(source.env_snapshot_json, dict)
        else build_environment_snapshot(environment, source.consumer_volume)
    )
    sim = Simulation(
        project_id=source.project_id,
        environment_id=source.environment_id or environment.id,
        status="QUEUED",
        consumer_volume=source.consumer_volume,
        seed=resolve_simulation_seed(source.seed, source.id),
        env_snapshot_json=env_snapshot,
    )
    db.add(sim)
    db.commit()
    db.refresh(sim)

    task = run_full_simulation.delay(sim.id)
    sim.task_id = task.id
    db.commit()
    db.refresh(sim)

    logger.info(
        "[API] Simulation rerun enqueued - source_id=%s simulation_id=%s "
        "task_id=%s seed=%s",
        source.id,
        sim.id,
        task.id,
        sim.seed,
    )

    _invalidate_simulation_caches(current_user.id)

    return SimulationStatusOut.model_validate(sim)


@router.get(
    "/{simulation_id}/reproducibility",
    response_model=SimulationReproducibilityOut,
    summary="Show a simulation's reproducibility manifest and verify identical-input runs",
    responses={
        200: {"description": "Reproducibility manifest returned"},
        404: {"description": "Simulation not found"},
    },
)
def get_simulation_reproducibility(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationReproducibilityOut:
    """Return a run's frozen inputs and how it compares to identical-input runs.

    The manifest shows the resolved seed, the environment snapshot frozen
    at enqueue time, and the run's stable result fingerprint. Completed
    sibling simulations in the same project with identical inputs (seed,
    consumer volume, environment snapshot) are listed with a ``match``
    verdict, so a founder can see at a glance whether a rerun was exact or
    whether something non-seed (input edits, code drift) changed the
    outcome.
    """
    source = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == current_user.id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Simulation not found")

    seed_used = resolve_simulation_seed(source.seed, source.id)
    env_snapshot = (
        copy.deepcopy(source.env_snapshot_json)
        if isinstance(source.env_snapshot_json, dict)
        else None
    )
    fingerprint = _stored_or_computed_fingerprint(source)

    notes: list[str] = []
    if source.status != "COMPLETED":
        notes.append("Fingerprint verification requires completed results.")
    if env_snapshot is None:
        notes.append(
            "This run predates environment snapshots; a rerun may use "
            "different environment inputs than the original."
        )
    if source.seed is None:
        notes.append(
            "No explicit seed was pinned; the legacy deterministic scheme "
            "provides the seed, so reruns remain reproducible."
        )

    siblings = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == source.project_id,
            Simulation.id != source.id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.id.asc())
        .limit(200)
        .all()
    )

    identical_runs: list[IdenticalInputRunOut] = []
    matched_runs = 0
    mismatched_runs = 0
    pending_runs = 0
    for other in siblings:
        if not inputs_are_identical(
            consumer_volume_a=source.consumer_volume,
            seed_used_a=seed_used,
            env_snapshot_a=env_snapshot,
            consumer_volume_b=other.consumer_volume,
            seed_used_b=resolve_simulation_seed(other.seed, other.id),
            env_snapshot_b=(
                copy.deepcopy(other.env_snapshot_json)
                if isinstance(other.env_snapshot_json, dict)
                else None
            ),
        ):
            continue
        other_fingerprint = _stored_or_computed_fingerprint(other)
        match: bool | None = None
        if fingerprint is not None and other_fingerprint is not None:
            match = fingerprint == other_fingerprint
        if match is True:
            matched_runs += 1
        elif match is False:
            mismatched_runs += 1
        else:
            pending_runs += 1
        identical_runs.append(
            IdenticalInputRunOut(
                simulation_id=other.id,
                status=other.status,
                created_at=other.created_at,
                fingerprint=other_fingerprint,
                match=match,
            )
        )

    if not identical_runs:
        notes.append(
            "No other completed simulation shares identical inputs "
            "(seed, consumer volume, environment snapshot)."
        )
    if mismatched_runs:
        mismatched_ids = [r.simulation_id for r in identical_runs if r.match is False]
        notes.append(
            "Identical-input runs produced different result fingerprints "
            f"(simulations {mismatched_ids}) — inputs or code changed between runs."
        )

    return SimulationReproducibilityOut(
        simulation_id=source.id,
        project_id=source.project_id,
        status=source.status,
        consumer_volume=source.consumer_volume,
        seed=source.seed,
        seed_used=seed_used,
        seed_pinned=source.seed is not None,
        env_snapshot=env_snapshot,
        exact_replay_supported=env_snapshot is not None,
        fingerprint=fingerprint,
        identical_input_runs=identical_runs,
        matched_runs=matched_runs,
        mismatched_runs=mismatched_runs,
        pending_runs=pending_runs,
        exact_replay_confirmed=bool(
            fingerprint is not None and matched_runs > 0 and mismatched_runs == 0
        ),
        notes=notes,
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


# Bounds for the portfolio launch-priority read. The digest composes
# the same six-pillar go/no-go reads as the per-project endpoint for
# up to MAX_PROJECTS projects, so the row caps keep the route
# bounded on tenants with large histories.
_PORTFOLIO_LAUNCH_PRIORITY_MAX_PROJECTS: int = 25
_PORTFOLIO_LAUNCH_PRIORITY_MAX_SIM_ROWS: int = 5000
_PORTFOLIO_LAUNCH_PRIORITY_MAX_ASSUMPTION_ROWS: int = 20000
_PORTFOLIO_LAUNCH_PRIORITY_ASSUMPTIONS_PER_PROJECT: int = 500
_PORTFOLIO_LAUNCH_PRIORITY_MAX_OUTCOME_ROWS: int = 5000


@router.get(
    "/portfolio-launch-priority",
    response_model=PortfolioLaunchPriorityOut,
    summary=(
        "Portfolio launch-priority digest — ranks the founder's "
        "projects by their go/no-go scorecards and answers "
        "'which project should I launch first?'"
    ),
    # Bounded per-project composition — same cap as the other
    # portfolio aggregates.
    dependencies=[Depends(rate_limit(limit=15, window_s=60))],
)
def get_portfolio_launch_priority(
    limit: int = Query(
        default=_PORTFOLIO_LAUNCH_PRIORITY_MAX_PROJECTS,
        ge=1,
        le=50,
        description=(
            "Maximum number of active projects to evaluate. Default "
            f"{_PORTFOLIO_LAUNCH_PRIORITY_MAX_PROJECTS}, capped at "
            "50 so the digest stays fast on large portfolios."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioLaunchPriorityOut:
    """Compose the portfolio launch-priority digest.

    Loads the user's active projects (newest first), the latest
    completed simulation, assumptions, and outcome freshness for
    each, then reuses the canonical per-project go/no-go builder so
    the portfolio ranking is exactly consistent with
    ``GET /projects/{id}/go-no-go``. The pure helper then buckets
    projects into LAUNCH_NOW / CONDITIONAL_LAUNCH / FIX_FIRST /
    PARK and emits the ranked launch sequence, top pick, and
    portfolio-wide focus pillar. No LLM call, no Celery dispatch.
    """
    projects = (
        db.query(
            Project.id,
            Project.title,
            Project.premortem_json,
            Project.competitive_json,
        )
        .filter(
            Project.user_id == current_user.id,
            Project.is_archived.is_(False),
        )
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(limit)
        .all()
    )
    if not projects:
        return PortfolioLaunchPriorityOut(
            **build_portfolio_launch_priority([])
        )

    project_ids = [row.id for row in projects]
    projects_by_id = {row.id: row for row in projects}

    # Latest completed simulation per project — one bounded scan,
    # deduped to the newest row per project in Python.
    sim_rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.created_at,
            Simulation.results_json,
            Simulation.signal_quality,
            Simulation.status,
        )
        .filter(
            Simulation.project_id.in_(project_ids),
            Simulation.status == "COMPLETED",
        )
        .order_by(
            Simulation.project_id.asc(),
            Simulation.created_at.desc(),
            Simulation.id.desc(),
        )
        .limit(_PORTFOLIO_LAUNCH_PRIORITY_MAX_SIM_ROWS)
        .all()
    )
    latest_sims: dict[int, Any] = {}
    for row in sim_rows:
        if row.project_id not in latest_sims:
            latest_sims[row.project_id] = row

    # Assumptions per project (category + sensitivity coverage),
    # capped per project so one giant project cannot starve the rest.
    assumption_rows = (
        db.query(
            Assumption.project_id,
            Assumption.category,
            Assumption.sensitivity,
            Assumption.is_hidden,
            Assumption.created_at,
        )
        .filter(Assumption.project_id.in_(project_ids))
        .order_by(
            Assumption.project_id.asc(),
            Assumption.created_at.desc(),
            Assumption.id.desc(),
        )
        .limit(_PORTFOLIO_LAUNCH_PRIORITY_MAX_ASSUMPTION_ROWS)
        .all()
    )
    assumptions_by_project: dict[int, list[dict[str, Any]]] = {}
    for row in assumption_rows:
        bucket = assumptions_by_project.setdefault(row.project_id, [])
        if len(bucket) >= _PORTFOLIO_LAUNCH_PRIORITY_ASSUMPTIONS_PER_PROJECT:
            continue
        bucket.append({
            "category": row.category,
            "sensitivity": row.sensitivity,
            "is_hidden": row.is_hidden,
            "created_at": row.created_at,
        })

    # Latest outcome timestamp per project (freshness + has-outcome).
    outcome_rows = (
        db.query(
            Outcome.project_id,
            Outcome.created_at,
        )
        .filter(Outcome.project_id.in_(project_ids))
        .order_by(
            Outcome.project_id.asc(),
            Outcome.created_at.desc(),
            Outcome.id.desc(),
        )
        .limit(_PORTFOLIO_LAUNCH_PRIORITY_MAX_OUTCOME_ROWS)
        .all()
    )
    latest_outcomes: dict[int, Any] = {}
    for row in outcome_rows:
        if row.project_id not in latest_outcomes:
            latest_outcomes[row.project_id] = row.created_at

    project_payloads: list[dict[str, Any]] = []
    for project_id in project_ids:
        project = projects_by_id[project_id]
        sim = latest_sims.get(project_id)
        assumptions = assumptions_by_project.get(project_id, [])

        readiness_payload = None
        trust_payload = None
        if sim is not None:
            readiness_payload = build_launch_checklist(
                results=sim.results_json,
                simulation_id=sim.id,
                project_id=project_id,
                status=sim.status,
                signal_quality=sim.signal_quality,
                visible_assumption_count=sum(
                    1
                    for assumption in assumptions
                    if not assumption["is_hidden"]
                ),
            )
            trust_payload = build_simulation_quality(
                simulation_id=sim.id,
                project_id=project_id,
                base_results=sim.results_json,
                status=sim.status,
                signal_quality=sim.signal_quality,
            )

        # A malformed legacy premortem blob (e.g. a JSON string)
        # must not 500 the whole portfolio digest — treat it as
        # "premortem not run yet", matching the per-project
        # endpoint's conservative fallback.
        premortem_data = project.premortem_json
        if not isinstance(premortem_data, dict):
            premortem_data = None
        premortem_payload = build_premortem_digest(premortem_data)

        competitive_payload = None
        competitive_data = project.competitive_json
        if isinstance(competitive_data, dict):
            competitors = competitive_data.get("competitors") or []
            high_threat_count = sum(
                1
                for competitor in competitors
                if isinstance(competitor, dict)
                and str(competitor.get("threat_level", "")).upper()
                == "HIGH"
            )
            competitive_payload = {
                "overall_competitive_position": (
                    competitive_data.get("overall_competitive_position")
                ),
                "high_threat_count": high_threat_count,
            }

        assumption_times = [
            assumption["created_at"]
            for assumption in assumptions
            if assumption["created_at"] is not None
        ]
        freshness_payload = {
            "latest_sim_completed_at": (
                sim.created_at if sim is not None else None
            ),
            "latest_assumption_at": (
                max(assumption_times) if assumption_times else None
            ),
            "latest_outcome_at": latest_outcomes.get(project_id),
        }

        coverage_payload = build_coverage_gaps(
            assumptions=[
                {
                    "category": assumption["category"],
                    "sensitivity": assumption["sensitivity"],
                    "is_hidden": assumption["is_hidden"],
                }
                for assumption in assumptions
            ],
        )

        go_no_go = build_go_no_go(
            readiness=readiness_payload,
            premortem=premortem_payload,
            competitive=competitive_payload,
            trust=trust_payload,
            freshness=freshness_payload,
            coverage=coverage_payload,
            project_id=project_id,
            latest_simulation_id=(
                sim.id if sim is not None else None
            ),
        )

        project_payloads.append({
            "project_id": project_id,
            "project_title": project.title,
            "latest_simulation_at": (
                sim.created_at if sim is not None else None
            ),
            "has_outcomes": project_id in latest_outcomes,
            "go_no_go": go_no_go.model_dump(),
        })

    payload = build_portfolio_launch_priority(project_payloads)
    return PortfolioLaunchPriorityOut(**payload)


@router.get(
    "/portfolio-launch-priority/export",
    response_class=StreamingResponse,
    summary=(
        "Spreadsheet export of the portfolio launch-priority digest — "
        "same data as /portfolio-launch-priority as multi-section CSV "
        "(or JSON when ?format=json)"
    ),
    # Same bounded per-project composition as the JSON endpoint.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_portfolio_launch_priority(
    limit: int = Query(
        default=_PORTFOLIO_LAUNCH_PRIORITY_MAX_PROJECTS,
        ge=1,
        le=50,
        description=(
            "Maximum number of active projects to evaluate. Default "
            f"{_PORTFOLIO_LAUNCH_PRIORITY_MAX_PROJECTS}, capped at "
            "50 so the digest stays fast on large portfolios."
        ),
    ),
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly multi-section document; "
            "``json`` returns the raw portfolio launch-priority "
            "payload as JSON."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Spreadsheet / machine export of the portfolio launch-priority digest.

    Reuses the exact same query + go/no-go composition as the JSON
    endpoint, so the export can never disagree with the dashboard. CSV
    output includes provenance metadata (generated_at, user_id,
    project_count) plus summary, bucket, and ranked launch-sequence
    sections. ``format=json`` returns the same digest payload in a
    metadata envelope for machine-to-machine consumers.
    """
    payload = get_portfolio_launch_priority(
        limit=limit,
        db=db,
        current_user=current_user,
    )
    data = payload.model_dump()
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "project_count": data.get("project_count", 0),
        "evaluated_count": data.get("evaluated_count", 0),
        "portfolio_verdict": data.get(
            "portfolio_verdict", "INSUFFICIENT_DATA"
        ),
        "format_version": "1",
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        body = json.dumps(
            {"metadata": metadata, "portfolio": data},
            default=str,
            indent=2,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="thecee-portfolio-launch-priority.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = portfolio_launch_priority_to_csv(data, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="thecee-portfolio-launch-priority.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


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
        conductor_diagnostics=results_json.get("conductor_diagnostics", {}),
        conductor_architect_timing=results_json.get(
            "conductor_architect_timing", {}
        ),
        pipeline_timing=results_json.get("pipeline_timing", {}),
        signal_quality=float(sim.signal_quality or 0.0),
        user_blindspots=user_blindspots,
    )


@router.get(
    "/{simulation_id}/calibration-transparency",
    response_model=CalibrationTransparencyOut,
    summary=(
        "Per-simulation calibration transparency — which learned architect "
        "corrections currently apply to this run's product type"
    ),
    responses=_JSON_200,
    # One simulation read plus a bounded architect_corrections lookup for
    # the run's product type; cap polling the same way the calibration
    # health views are bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_calibration_transparency(
    simulation_id: int,
    corrections_limit: int = Query(
        default=DEFAULT_CORRECTIONS_LIMIT,
        ge=1,
        le=MAX_CORRECTIONS_LIMIT,
        description=(
            "Maximum number of strongest correction rows to return "
            "(sorted by |scalar - 1| descending)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalibrationTransparencyOut:
    """Show the learning layer's current influence on a completed run.

    Uses the same ``architect_corrections`` table and selection logic the
    Conductor loads at run time (product type filter, confidence gate,
    exact-cluster vs ``ALL`` fallback), so the coverage shown here is what
    a re-run of this product type would apply *today*. ``by_architect`` and
    ``by_cluster`` roll up coverage across the deterministic architect
    stack; ``corrections`` lists the strongest adjustments.
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
                f"Simulation is {sim.status} — calibration transparency "
                "requires completed results."
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
    product_type_value = product_type.value

    correction_rows = db.execute(
        text("""
            SELECT architect_name, product_type, product_attribute,
                   cluster_id, correction_scalar, confidence_weight,
                   effective_sample_count, scope
            FROM architect_corrections
            WHERE product_type = :pt
            ORDER BY architect_name, cluster_id
        """),
        {"pt": product_type_value},
    ).mappings().all()

    diagnostics = (sim.results_json or {}).get("conductor_diagnostics") or {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    recorded = diagnostics.get("applied_corrections")
    recorded_applied: int | None = coerce_recorded_applied_corrections(recorded)

    payload = build_calibration_transparency(
        [dict(row) for row in correction_rows],
        product_type=product_type_value,
        clusters=_registry.all_clusters(),
        architect_names=ARCHITECT_STACKS.get(product_type, []),
        simulation_id=sim.id,
        project_id=sim.project_id,
        corrections_limit=corrections_limit,
    )
    payload["recorded_applied_corrections"] = recorded_applied
    return CalibrationTransparencyOut(**payload)


@router.get(
    "/{simulation_id}/progress",
    summary=(
        "Live percent progress while a simulation is running, including "
        "per-cluster updates during the conductor phase"
    ),
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

    pct_map = {"QUEUED": 0, "RUNNING": 50, "COMPLETED": 100, "FAILED": 0, "CANCELLED": 0}
    pct = pct_map.get(sim.status, 0)
    stage: str | None = None
    cluster_id: str | None = None
    clusters_completed: int | None = None
    clusters_total: int | None = None

    if sim.status == "RUNNING" and sim.task_id:
        try:
            task_result = celery_app.AsyncResult(sim.task_id)
            if task_result.state == "PROGRESS":
                meta = task_result.info or {}
                if isinstance(meta, dict):
                    pct = meta.get("pct", 50)
                    stage = meta.get("stage")
                    cluster_id = meta.get("cluster_id")
                    clusters_completed = meta.get("clusters_completed")
                    clusters_total = meta.get("clusters_total")
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
        "stage": stage,
        "cluster_id": cluster_id,
        "clusters_completed": clusters_completed,
        "clusters_total": clusters_total,
        "agents_processed": agents_processed,
        "agents_total": sim.consumer_volume,
        "elapsed_seconds": round(elapsed, 1),
        "task_id": sim.task_id,
        "error": sim.error_message,
        "results": sim.results_json if sim.status == "COMPLETED" else None,
    }


@router.post(
    "/{simulation_id}/cancel",
    response_model=SimulationCancelOut,
    summary="Cancel a queued or running simulation",
    responses={
        200: {"description": "Simulation cancelled"},
        404: {"description": "Simulation not found"},
        409: {"description": "Simulation is not cancellable in its current state"},
    },
    # Mutating lifecycle endpoint — 10/min/IP is plenty for a human
    # stopping a run and bounds accidental script loops.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def cancel_simulation(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationCancelOut:
    """Stop a simulation the caller owns before it completes.

    Queued tasks are revoked so they never start. Running tasks observe
    the ``CANCELLED`` row at their next cluster boundary (via
    ``Conductor.run(cancel_check=...)``) and unwind cleanly — no partial
    results are persisted and no retries are burned. Completed or failed
    simulations cannot be cancelled.

    The QUEUED/RUNNING → CANCELLED write is atomic with the worker's
    QUEUED/RUNNING → COMPLETED write: if the run finishes first, this
    call returns 409 with the fresh status instead of overwriting it.
    The API is the sole emitter of ``simulation.cancelled`` webhooks, so
    a queued task that races past its revoke cannot double-deliver.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status not in {"QUEUED", "RUNNING"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation {simulation_id} is {sim.status} and "
                "cannot be cancelled."
            ),
        )

    if sim.task_id:
        try:
            celery_app.control.revoke(sim.task_id, terminate=False)
        except Exception as exc:
            logger.warning(
                "[Simulation] revoke failed - simulation_id=%s task_id=%s error=%s",
                simulation_id,  # codeql[py/log-injection]: FastAPI coerces the path param to int before the handler
                sim.task_id,
                exc,  # codeql[py/log-injection]: internal library exception text, server-side log only
            )

    cancelled_at = datetime.now(UTC)
    # Guarded terminal transition: only QUEUED/RUNNING rows may become
    # CANCELLED. If the worker completed (or failed) the simulation
    # between the ownership read above and this UPDATE, the row is no
    # longer cancellable and we must not overwrite its terminal state —
    # the request turns into a 409 with the fresh status.
    result = db.execute(
        text(
            """
            UPDATE simulations
            SET status = 'CANCELLED',
                error_message = :msg,
                updated_at = :u
            WHERE id = :sid
              AND status IN ('QUEUED', 'RUNNING')
            """
        ),
        {"msg": "Cancelled by user", "u": cancelled_at, "sid": simulation_id},
    )
    if int(getattr(result, "rowcount", 1) or 0) == 0:
        db.rollback()
        fresh_status = db.execute(
            text("SELECT status FROM simulations WHERE id = :sid"),
            {"sid": simulation_id},
        ).scalar()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation {simulation_id} is {fresh_status} and "
                "cannot be cancelled."
            ),
        )

    sim.status = "CANCELLED"
    sim.error_message = "Cancelled by user"
    sim.updated_at = cancelled_at
    db.commit()
    db.refresh(sim)

    metrics.sim_cancelled()
    sync_broadcast(
        simulation_id,
        "CANCELLED",
        "Cancelled by user",
        0,
    )

    # The API is the single webhook emitter for cancellation: the worker
    # observes the CANCELLED row (which this request just committed) and
    # unwinds without re-enqueueing, so a queued task that races past its
    # revoke cannot cause a duplicate simulation.cancelled delivery.
    try:
        _enqueue_simulation_webhooks(
            db,
            project_id=sim.project_id,
            simulation_id=simulation_id,
            status="CANCELLED",
            conversion_rate=None,
            error="Cancelled by user",
        )
    except Exception as exc:
        logger.warning(
            "[Simulation] webhook enqueue on cancel skipped - "
            "simulation_id=%s error=%s",
            simulation_id,  # codeql[py/log-injection]: FastAPI coerces the path param to int before the handler
            exc,  # codeql[py/log-injection]: internal library exception text, server-side log only
        )

    _invalidate_simulation_caches(current_user.id)

    logger.info(
        "[Simulation] Cancelled by user - simulation_id=%s task_id=%s",
        simulation_id,  # codeql[py/log-injection]: FastAPI coerces the path param to int before the handler
        sim.task_id,
    )

    return SimulationCancelOut(
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        task_id=sim.task_id,
        cancelled_at=cancelled_at,
    )


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


@router.get(
    "/{simulation_id}/stress-scenarios/export",
    response_class=StreamingResponse,
    summary="Export stress-scenario resilience analysis as CSV, JSON, or Markdown",
)
def export_simulation_stress_scenarios(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly tables; ``json`` returns the raw "
            "resilience payload; ``md`` returns a founder-facing brief."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export the stress-scenario resilience analysis for a simulation.

    Reuses the same projection as
    ``GET /{simulation_id}/stress-scenarios`` — the response body is just a
    different serialization of that result, so founders can drop the
    recession / price-war / viral-catalyst / channel-bottleneck comparison
    into a spreadsheet or share it with a team.
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

    result = get_simulation_stress_scenarios(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_id": simulation_id,
        "project_id": result.get("project_id"),
        "format_version": stress_scenarios_export_FORMAT_VERSION,
    }

    if fmt == "json":
        body = stress_scenarios_to_json(result, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="stress-scenarios-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "md":
        body = stress_scenarios_to_markdown(result, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="stress-scenarios-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = stress_scenarios_to_csv(result, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="stress-scenarios-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


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
    "/{simulation_id}/cohort-retention/export",
    response_class=StreamingResponse,
    summary="Export the cohort-retention projection as CSV, JSON, or Markdown",
)
def export_cohort_retention(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly tables; ``json`` returns the raw "
            "projection payload; ``md`` returns a founder-facing brief."
        ),
    ),
    cluster_limit: int = Query(
        default=52,
        ge=1,
        le=52,
        description="Maximum number of cluster profiles to include.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export the cohort-retention projection for a simulation.

    Reuses the same projection as
    ``GET /{simulation_id}/cohort-retention`` — the response body is just a
    different serialization of that result, so founders can drop survival
    curves, churn risk, and LTV estimates into a spreadsheet or share them
    with a team.
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

    result = get_cohort_retention(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
        cluster_limit=cluster_limit,
    )
    result_data = (
        result.model_dump() if hasattr(result, "model_dump") else dict(result)
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_id": simulation_id,
        "project_id": result_data.get("project_id"),
        "format_version": cohort_retention_export_FORMAT_VERSION,
    }

    if fmt == "json":
        body = cohort_retention_to_json(result, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="cohort-retention-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "md":
        body = cohort_retention_to_markdown(result, metadata=metadata).encode(
            "utf-8"
        )
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="cohort-retention-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = cohort_retention_to_csv(result, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="cohort-retention-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
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
    "/{simulation_id}/buyer-personas",
    response_model=BuyerPersonasOut,
    summary="Rank buyer personas from cluster profiles + simulation conversion",
    responses=_JSON_200,
)
def get_buyer_personas(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(
        default=10,
        description=(
            "Maximum number of ranked persona cards to return "
            "(clamped to 1–52)."
        ),
    ),
    benchmark: float = Query(
        default=0.05,
        description=(
            "Conversion-rate benchmark used to score gaps "
            "(clamped to 0.01–0.5)."
        ),
    ),
) -> BuyerPersonasOut:
    """
    Build ranked buyer-persona briefs from completed results:

      * Full registry profile (description, 8 traits, behavior pattern,
        affinities, demographics, known failure modes).
      * Deterministic messaging angle per persona.
      * Risk watchlist + segment-aware recommended focus.

    Ranking and segments reuse the cluster-opportunity matrix so GTM
    analytics and persona cards can never disagree. Pure analytics — no
    Celery, no LLM.
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
                f"Simulation is {sim.status} — buyer personas require "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    effective_limit = limit if isinstance(limit, int) else 10
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
            "description": cluster.description,
            "population_weight": cluster.population_weight,
            "base_traits": dict(cluster.base_traits),
            "trait_variance": dict(cluster.trait_variance),
            "dominant_behavior_pattern": cluster.dominant_behavior_pattern,
            "known_failure_modes": list(cluster.known_failure_modes),
            "product_affinities": list(cluster.product_affinities),
            "demographic_profile": dict(cluster.demographic_profile),
        }
        for cid, cluster in _clusters_map.items()
    }

    return build_buyer_personas(
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
    "/{simulation_id}/market-concentration/export",
    response_class=StreamingResponse,
    summary="Export the demand-concentration read as CSV or JSON",
    # Pure post-hoc composition of the completed simulation payload; cap
    # polling so a stray dashboard loop can't drive repeated HHI recomputes.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def export_market_concentration(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the multi-section "
            "spreadsheet; ``json`` returns the raw market-concentration "
            "payload. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the demand-concentration read for a completed simulation.

    Reuses the exact composition path as
    ``GET /simulations/{id}/market-concentration``, so the export can never
    disagree with the dashboard. ``format=csv`` renders the HHI summary,
    one row per cluster demand share, fragility flags and recommendations
    with a UTF-8 BOM so Excel decodes non-Latin cluster names correctly;
    ``format=json`` returns the raw concentration payload for machine
    consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    concentration = get_market_concentration(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": concentration.project_id,
    }

    if fmt == "json":
        body = market_concentration_to_json(
            concentration,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="market-concentration-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    body = market_concentration_to_csv(
        concentration,
        metadata=metadata,
    ).encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="market-concentration-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
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
    "/{simulation_id}/pricing-optimization/export",
    response_class=StreamingResponse,
    summary=(
        "Export pricing optimization as CSV, JSON, or Markdown"
    ),
    # Same DB read + conductor recompute cost as the JSON pricing
    # optimization endpoint; cap polling so a dashboard loop can't
    # drive repeated scenario recomputes.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_pricing_optimization(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a multi-section "
            "spreadsheet; ``json`` returns the raw pricing-optimization "
            "payload; ``md`` returns a founder-facing Markdown brief. "
            "Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the pricing-optimization read for a completed simulation."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; "
                "expected 'csv', 'json', or 'md'"
            ),
        )

    payload = get_pricing_optimization(
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
        "format_version": PRICING_OPTIMIZATION_FORMAT_VERSION,
        "simulation_id": simulation_id,
        "project_id": payload.project_id,
    }

    if fmt == "json":
        body = pricing_optimization_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="pricing-optimization-'
                    f'{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    if fmt == "md":
        md_text = pricing_optimization_to_markdown(
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
                    'attachment; filename="pricing-optimization-'
                    f'{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = pricing_optimization_to_csv(
        payload,
        metadata=metadata,
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="pricing-optimization-'
                f'{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
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
    "/{simulation_id}/validation-experiment-plan/schedule",
    response_model=ValidationSprintScheduleOut,
    summary="Fit the validation sprint into a real calendar and budget",
    responses=_JSON_200,
)
def get_validation_experiment_schedule(
    simulation_id: int,
    max_days: int = Query(
        default=14,
        ge=1,
        le=90,
        description="Sequential days available for running experiments.",
    ),
    budget_tier: COST_TIER_LITERAL = Query(
        default="LOW",
        description="Maximum allowed experiment cost tier (FREE < LOW < MEDIUM).",
    ),
    max_parallel: int = Query(
        default=1,
        ge=1,
        le=4,
        description="Concurrent experiment tracks the founder can run.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationSprintScheduleOut:
    """
    Constrained validation schedule for a completed simulation.

    Takes the full experiment plan and re-fits it to an explicit envelope:
    ``max_days`` of run time across up to ``max_parallel`` tracks and a
    ``budget_tier`` ceiling. Experiments are kept greedily in
    validation-ROI order while they clear all three constraints; everything
    else is deferred with a founder-readable reason. Pure post-hoc
    analysis — no Celery dispatch, no LLM calls.
    """
    plan = get_validation_experiment_plan(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )
    return schedule_validation_sprint(
        plan,
        max_days=max_days,
        budget_tier=budget_tier,
        max_parallel=max_parallel,
    )


@router.get(
    "/{simulation_id}/compare/{baseline_id}",
    response_model=SimulationRunDiffOut,
    summary="Diff a completed run against a baseline run",
    responses=_JSON_200,
)
def get_simulation_comparison(
    simulation_id: int,
    baseline_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationRunDiffOut:
    """
    Funnel-level diff between two completed simulations.

    Where ``sim-diff`` compares domain findings and ``cluster-diff``
    compares clusters inside one run, this endpoint answers "did the
    re-run move the projection?" — headline conversion in percentage
    points, per-stage drop-off changes, and the cluster movers behind
    the shift. Pure post-hoc analysis over stored ``results_json``.
    """
    if baseline_id == simulation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="baseline_id must differ from simulation_id",
        )

    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    baseline = _get_owned_simulation(baseline_id, current_user.id, db)

    for role, row in (("compared", sim), ("baseline", baseline)):
        if row.status == "FAILED":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{role} simulation failed: "
                    f"{row.error_message or 'unknown error'}"
                ),
            )
        if row.status != "COMPLETED":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{role} simulation is {row.status} — comparison "
                    "requires completed results."
                ),
            )
        if not row.results_json:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{role} simulation completed but results_json is empty."
                ),
            )

    return build_run_diff(
        simulation_id=sim.id,
        baseline_id=baseline.id,
        current_results=sim.results_json or {},
        baseline_results=baseline.results_json or {},
        current_signal=(
            float(sim.signal_quality) if sim.signal_quality is not None else None
        ),
        baseline_signal=(
            float(baseline.signal_quality)
            if baseline.signal_quality is not None
            else None
        ),
        project_id=sim.project_id,
    )


@router.get(
    "/{simulation_id}/validation-experiment-plan/export",
    response_class=StreamingResponse,
    summary="Export the validation sprint plan as CSV, JSON, or Markdown",
    # Pure post-hoc composition of the completed simulation payload; cap
    # polling so a stray dashboard loop can't drive repeated ROI recomputes.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def export_validation_experiment_plan(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the multi-section "
            "spreadsheet; ``json`` returns the raw validation-experiment-plan "
            "payload; ``md`` returns a founder-facing Markdown brief. "
            "Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the validation sprint plan for a completed simulation.

    Reuses the exact composition path as
    ``GET /simulations/{id}/validation-experiment-plan``, so the export can
    never disagree with the dashboard. ``format=csv`` renders the sprint
    summary and one row per planned experiment (method, cost tier, duration,
    sample target, success threshold, go/no-go rule) with a UTF-8 BOM so
    Excel decodes non-Latin text correctly; ``format=json`` returns the raw
    plan payload for machine consumers; ``format=md`` returns a founder-facing
    Markdown brief with the sprint summary, per-experiment table, go/no-go
    rules, and meta.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv', 'json', or 'md'",
        )

    plan = get_validation_experiment_plan(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": plan.project_id,
    }

    if fmt == "json":
        body = validation_experiment_plan_to_json(
            plan,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="validation-experiment-plan-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    if fmt == "md":
        body = validation_experiment_plan_to_markdown(
            plan,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="validation-experiment-plan-{simulation_id}.md"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    body = validation_experiment_plan_to_csv(
        plan,
        metadata=metadata,
    ).encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="validation-experiment-plan-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


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


@router.get(
    "/architect-stack",
    response_model=ArchitectStackRegistryOut,
    summary="Deterministic architect stack and product-type coverage registry",
    responses=_JSON_200,
    # Read-only, deterministic, but walkable by an authenticated actor to
    # enumerate the full architect registry — cap at 30/min/IP like the
    # other registry-style routes.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_architect_stack(
    product_type: str | None = Query(
        default=None,
        max_length=32,
        description=(
            "Optional product-type filter, e.g. ``saas`` or "
            "``consumer_hardware``. Without it the full registry and "
            "per-product-type coverage are returned."
        ),
    ),
    current_user: User = Depends(get_current_user),
) -> ArchitectStackRegistryOut:
    """Expose the conductor's deterministic architect stack.

    Every simulation runs the architects listed in the requested product
    type's stack in order; other registered architects are deliberately
    excluded for that product type. This endpoint makes that decision
    visible: founders can see which domain specialists actually evaluated
    their brief, operators can see universal vs specialised coverage, and
    the product-coverage table surfaces any stack entry that is missing
    from the live registry.
    """
    try:
        payload = build_architect_stack_registry(
            registry=_architect_registry,
            stacks=ARCHITECT_STACKS,
            product_type=product_type,
            all_product_types=list(ProductType),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ArchitectStackRegistryOut(**payload)


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
    "/{simulation_id}/first-customers",
    response_model=FirstCustomersOut,
    summary=(
        "First-customer trajectory: time to 10/100/1000 customers "
        "from weighted conversion + expected monthly traffic"
    ),
    responses=_JSON_200,
)
def get_first_customers(
    simulation_id: int,
    monthly_visitors: int = Query(
        DEFAULT_MONTHLY_VISITORS,
        ge=MIN_MONTHLY_VISITORS,
        le=MAX_MONTHLY_VISITORS,
        description=(
            "Expected website/app visitors per month; used as the "
            "linear traffic assumption for the milestone timeline"
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FirstCustomersOut:
    """Project the first customer milestones for a completed run.

    Turns the simulation's weighted conversion into a founder-facing
    timeline: at ``monthly_visitors`` expected monthly visitors, when
    do the first 10 / 100 / 1,000 customers arrive, how many visitors
    does each milestone require, and which consumer clusters supply
    the first wave? Pure post-hoc analytics — no Celery, no LLM.
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
                f"Simulation is {sim.status} — the first-customer "
                "timeline requires completed results."
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

    payload = build_first_customers(
        sim.results_json,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        monthly_visitors=monthly_visitors,
        cluster_registry=registry,
        signal_quality=(
            float(sim.signal_quality)
            if sim.signal_quality is not None
            else None
        ),
    )
    return FirstCustomersOut(**payload)


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


def _build_investor_readiness_payload(
    simulation_id: int,
    current_user_id: int,
    db: Session,
    market_size: int = DEFAULT_MARKET_SIZE,
    target_market_fraction: float = DEFAULT_TARGET_MARKET_FRACTION,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    purchase_frequency_per_year: float = DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
    gross_margin: float = 0.60,
    assumed_cac: float = 0.0,
) -> InvestorReadinessOut:
    """Compute the investor-readiness digest for an owned simulation."""
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
                f"Simulation is {sim.status} — investor-readiness "
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

    # The project's visible assumptions shape the architect stack for the
    # recomputed reads; feed them through so the digest matches the actual
    # run instead of defaulting to neutral inputs.
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

    # Recompute the deterministic architect stack once so unit economics,
    # retention and defensibility reads share the same per-cluster metrics.
    # No DB writes are performed (no session passed to run()).
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
    registry_dict = {
        str(entry["cluster_id"]): {
            "name": entry["name"],
            "population_weight": entry["population_weight"],
        }
        for entry in registry
    }

    results = sim.results_json
    signal_quality = (
        float(sim.signal_quality) if sim.signal_quality is not None else None
    )

    market = build_market_sizing(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        market_size=market_size,
        target_market_fraction=target_market_fraction,
        average_order_value=average_order_value,
        purchase_frequency_per_year=purchase_frequency_per_year,
        cluster_registry=registry_dict,
        signal_quality=signal_quality,
    )
    economics = build_unit_economics(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        conductor_results=conductor_results,
        cluster_registry=registry,
        average_order_value=aov,
        gross_margin=gross_margin,
        purchase_frequency_per_year=purchase_frequency_per_year,
        assumed_cac=assumed_cac,
    )
    retention = build_retention_churn(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )
    moat = build_competitive_moat(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type_name,
    )
    readiness = build_launch_checklist(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        visible_assumption_count=len(assumptions),
        product_type=product_type_name,
        cluster_registry=registry,
    )
    quality = build_simulation_quality(
        simulation_id=sim.id,
        project_id=sim.project_id,
        base_results=results,
        status=sim.status,
        signal_quality=signal_quality,
    )

    return build_investor_readiness(
        results,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        signal_quality=signal_quality,
        product_type=product_type_name,
        market=market,
        economics=economics,
        retention=retention,
        moat=moat,
        readiness=readiness,
        quality=quality,
        domain_findings=(results or {}).get("domain_findings") or [],
    )


@router.get(
    "/{simulation_id}/investor-readiness",
    response_model=InvestorReadinessOut,
    summary=(
        "Investor readiness: one scorecard of market, unit economics, "
        "retention, defensibility, launch readiness and data trust"
    ),
    responses=_JSON_200,
)
def get_investor_readiness(
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
        ge=1.0,
        description="Purchases per customer per year",
    ),
    gross_margin: float = Query(
        0.60,
        ge=0.0,
        le=1.0,
        description="Fraction of revenue retained after cost of goods",
    ),
    assumed_cac: float = Query(
        0.0,
        ge=0.0,
        description="Founder-observed blended CAC (0 derives a default)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvestorReadinessOut:
    """
    Investor-facing digest for a completed simulation.

    Combines six deterministic reads into one scorecard: market size,
    unit economics, retention, defensibility, launch readiness and data
    trust. Each pillar gets a 0..100 score; the available pillars are
    weighted into an overall investor score with strengths, risks and
    top actions. Pure post-hoc analytics — no Celery, no LLM, no DB
    writes.
    """
    return _build_investor_readiness_payload(
        simulation_id=simulation_id,
        current_user_id=current_user.id,
        db=db,
        market_size=market_size,
        target_market_fraction=target_market_fraction,
        average_order_value=average_order_value,
        purchase_frequency_per_year=purchase_frequency_per_year,
        gross_margin=gross_margin,
        assumed_cac=assumed_cac,
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
    "/{simulation_id}/journey",
    response_model=JourneyAnalyticsOut,
    summary=(
        "Journey analytics: purchase/abandon probabilities, most probable "
        "customer journeys, exit-stage leaks, and highest-leverage "
        "funnel transitions"
    ),
    responses=_JSON_200,
)
def get_simulation_journey_analytics(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JourneyAnalyticsOut:
    """
    Journey analytics for a completed simulation.

    Derives absorbing-Markov-chain metrics from the per-cluster transition
    matrices persisted with the run: purchase/abandon probability, expected
    journey length and revisits, exit-stage distribution, most probable
    journeys, and a ranked list of which 5pp transition improvements would
    lift conversion the most. Pure post-hoc analytics — no Celery, no LLM,
    no DB writes.
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
                f"Simulation is {sim.status} — journey analytics requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    results = sim.results_json if isinstance(sim.results_json, dict) else {}
    raw_matrices = results.get("per_cluster_matrices")
    if not deserialise_per_cluster_matrices(raw_matrices):
        raise HTTPException(
            status_code=404,
            detail=(
                "Journey analytics are unavailable for this simulation — "
                "per-cluster journey data is persisted for runs started "
                "after this version. Re-run the simulation to generate it."
            ),
        )

    payload = build_journey_analytics(
        raw_matrices,
        results.get("cluster_weights"),
    )
    return JourneyAnalyticsOut(
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        **payload,
    )


def _journey_payload_for_simulation(sim: Simulation) -> dict[str, Any]:
    """Return the full journey-analytics payload for a simulation.

    Applies the same status / results gates as
    :func:`get_simulation_journey_analytics` so journey endpoints never
    disagree about which simulations are eligible.
    """
    results, _matrices = _journey_data_for_simulation(sim)
    return build_journey_analytics(
        results.get("per_cluster_matrices"),
        results.get("cluster_weights"),
    )


def _journey_data_for_simulation(
    sim: Simulation,
) -> tuple[dict[str, Any], dict[str, dict[tuple[str, str], float]]]:
    """Validate a simulation and return its journey results + matrices.

    Shared status / results gates for every journey endpoint (analytics,
    export, and benchmark) so they can never disagree about which
    simulations are eligible. Returns the raw ``results_json`` dict and the
    deserialised per-cluster transition matrices.
    """
    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Simulation is {sim.status} — journey analytics requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    results = sim.results_json if isinstance(sim.results_json, dict) else {}
    matrices = deserialise_per_cluster_matrices(results.get("per_cluster_matrices"))
    if not matrices:
        raise HTTPException(
            status_code=404,
            detail=(
                "Journey analytics are unavailable for this simulation — "
                "per-cluster journey data is persisted for runs started "
                "after this version. Re-run the simulation to generate it."
            ),
        )
    return results, matrices


@router.get(
    "/{simulation_id}/journey/export",
    response_class=StreamingResponse,
    summary=(
        "Export the journey-analytics payload as CSV (or JSON with "
        "?format=json)"
    ),
)
def export_simulation_journey_analytics(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly multi-section table; ``json`` returns the "
            "raw journey-analytics payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the journey analytics for a completed simulation.

    The CSV export mirrors the JSON endpoint's summary, exit-stage leaks,
    most probable paths, leverage rankings, per-cluster detail, and key
    insights in one spreadsheet. ``format=json`` returns the exact payload
    for machine consumers. Pure post-hoc analytics — no Celery, no LLM, no
    DB writes.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv' or "
                "'json'"
            ),
        )

    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    payload = _journey_payload_for_simulation(sim)
    payload = {
        **payload,
        "simulation_id": sim.id,
        "project_id": sim.project_id,
        "status": sim.status,
    }

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_id": sim.id,
        "project_id": sim.project_id,
        "format_version": JOURNEY_ANALYTICS_FORMAT_VERSION,
    }

    if fmt == "json":
        text = journey_analytics_to_json(payload, metadata=metadata)
        body = text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="journey-analytics.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = journey_analytics_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="journey-analytics.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{simulation_id}/journey/benchmark",
    response_model=JourneyBenchmarkOut,
    summary=(
        "Journey benchmark: how this simulation's funnel ranks against the "
        "founder's other completed simulations"
    ),
    responses=_JSON_200,
)
def get_simulation_journey_benchmark(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JourneyBenchmarkOut:
    """
    Benchmark a completed simulation's customer journey against the founder's
    own portfolio history.

    The cohort is every other completed simulation owned by the user that
    persisted per-cluster journey data. The response compares purchase
    probability (median/mean/percentiles and this simulation's percentile
    rank), journey length and revisits, per-stage leak medians, and the modal
    primary exit stage, then translates the comparison into plain-language
    insights. Pure post-hoc analytics — no Celery, no LLM, no DB writes.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    results, _matrices = _journey_data_for_simulation(sim)
    current_payload = summarise_journey_matrices(
        results.get("per_cluster_matrices"),
        results.get("cluster_weights"),
    )
    if current_payload is None:
        # _journey_data_for_simulation guarantees non-empty matrices; this
        # guards against a hypothetical empty aggregate edge case.
        raise HTTPException(
            status_code=404,
            detail=(
                "Journey analytics are unavailable for this simulation — "
                "per-cluster journey data is persisted for runs started "
                "after this version. Re-run the simulation to generate it."
            ),
        )

    rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.results_json,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Project.user_id == current_user.id,
            Simulation.id != simulation_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .all()
    )

    cohort_summaries: list[dict[str, Any]] = []
    skipped_without_journey_data = 0
    for row in rows:
        results = row.results_json if isinstance(row.results_json, dict) else {}
        summary = summarise_journey_matrices(
            results.get("per_cluster_matrices"),
            results.get("cluster_weights"),
        )
        if summary is None:
            skipped_without_journey_data += 1
            continue
        cohort_summaries.append(summary)

    payload = build_journey_benchmark(current_payload, cohort_summaries)
    payload["meta"] = {
        **payload["meta"],
        "raw_completed_count": len(rows),
        "skipped_without_journey_data": skipped_without_journey_data,
    }
    return JourneyBenchmarkOut(
        simulation_id=sim.id,
        project_id=sim.project_id,
        **payload,
    )


@router.get(
    "/{simulation_id}/journey/trend",
    response_model=JourneyTrendOut,
    summary=(
        "Journey trend: how funnel health has evolved across the founder's "
        "completed simulations"
    ),
    responses=_JSON_200,
)
def get_simulation_journey_trend(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JourneyTrendOut:
    """
    Show whether a founder's funnel health is improving across simulations.

    Every completed simulation owned by the user (oldest first, including
    the requested one) is reduced to a lightweight funnel summary. The
    response includes per-simulation purchase probability, journey length,
    revisits and primary exit stage with deltas; best/worst runs; a trend
    slope and stability score; recent momentum; per-stage leak medians; and
    plain-language insights. The requested simulation is flagged
    ``is_anchor`` and ranked against the founder's other simulations.
    Pure post-hoc analytics — no Celery, no LLM, no DB writes.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    # Validate the anchor simulation has persisted journey data first, so
    # the trend can never silently omit the run the founder asked about.
    _journey_data_for_simulation(sim)

    rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.created_at,
            Simulation.results_json,
        )
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Project.user_id == current_user.id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.asc(), Simulation.id.asc())
        .all()
    )

    trend_rows: list[dict[str, Any]] = []
    for row in rows:
        row_results = (
            row.results_json if isinstance(row.results_json, dict) else {}
        )
        summary = summarise_journey_matrices(
            row_results.get("per_cluster_matrices"),
            row_results.get("cluster_weights"),
        )
        trend_rows.append(
            {
                "simulation_id": row.id,
                "project_id": row.project_id,
                "created_at": row.created_at,
                "journey_summary": summary,
            }
        )

    payload = build_journey_trend(
        trend_rows,
        anchor_simulation_id=sim.id,
        project_id=sim.project_id,
    )
    payload["generated_at"] = datetime.now(tz=UTC).isoformat()
    return JourneyTrendOut(**payload)


@router.get(
    "/{simulation_id}/journey/trend/export",
    response_class=StreamingResponse,
    summary=(
        "Export the journey trend as CSV (or JSON with ?format=json)"
    ),
)
def export_simulation_journey_trend(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly multi-section table; ``json`` returns the "
            "raw journey-trend payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the journey trend in CSV (default) or JSON form.

    Delegates to :func:`get_simulation_journey_trend`, so the exported
    portfolio series can never disagree with the JSON endpoint. The CSV
    mirrors the headline trend statistics, purchase statistics, recent
    momentum, best/worst runs, per-simulation points, stage-leak medians,
    latest stage leaks, and insights in one spreadsheet. ``format=json``
    returns the exact payload for machine consumers. Pure post-hoc
    analytics — no Celery, no LLM, no DB writes.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv' or "
                "'json'"
            ),
        )

    trend = get_simulation_journey_trend(
        simulation_id=simulation_id,
        db=db,
        current_user=current_user,
    )
    payload = trend.model_dump()
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_id": simulation_id,
        "project_id": payload.get("project_id"),
        "format_version": JOURNEY_TREND_FORMAT_VERSION,
    }

    if fmt == "json":
        text = journey_trend_to_json(payload, metadata=metadata)
        body = text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="journey-trend.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = journey_trend_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="journey-trend.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


# Category benchmark scans completed simulations across all users, so the
# payload is cached for a few minutes and the path is rate-limited to keep
# accidental dashboard loops from triggering repeated platform-wide scans.
_JOURNEY_CATEGORY_BENCHMARK_CACHE_TTL_S: int = 300
_JOURNEY_CATEGORY_BENCHMARK_CACHE_NAMESPACE: str = "journey-category-benchmark"


@router.get(
    "/{simulation_id}/journey/category-benchmark",
    response_model=JourneyCategoryBenchmarkOut,
    summary=(
        "Journey category benchmark: how this simulation's funnel ranks "
        "against completed simulations in the same product category"
    ),
    responses=_JSON_200,
    # Platform-wide cohort scan — cap path-spam at 20/min/IP so a runaway
    # dashboard script can't drive repeated full-table JSONB scans.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def get_simulation_journey_category_benchmark(
    simulation_id: int,
    limit: int = Query(
        default=200,
        ge=10,
        le=1000,
        description=(
            "Maximum number of same-category completed simulations to "
            "include in the cohort, newest first."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JourneyCategoryBenchmarkOut:
    """
    Benchmark a completed simulation's customer journey against every other
    completed simulation in the same product category across all TheCee users.

    The category is taken from the simulation's own
    ``product_type_detected`` result (falling back to ``saas`` for legacy
    runs). The response uses the same funnel cohort statistics and percentile
    ranking as the personal journey benchmark, but the cohort is the latest
    same-category simulations platform-wide. Only aggregate statistics are
    returned — no individual simulation from another user is ever exposed.
    Pure post-hoc analytics — no Celery, no LLM, no DB writes.
    """
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    results, _matrices = _journey_data_for_simulation(sim)
    current_payload = summarise_journey_matrices(
        results.get("per_cluster_matrices"),
        results.get("cluster_weights"),
    )
    if current_payload is None:
        # _journey_data_for_simulation guarantees non-empty matrices; this
        # guards against a hypothetical empty aggregate edge case.
        raise HTTPException(
            status_code=404,
            detail=(
                "Journey analytics are unavailable for this simulation — "
                "per-cluster journey data is persisted for runs started "
                "after this version. Re-run the simulation to generate it."
            ),
        )

    category = str(results.get("product_type_detected") or "saas").strip().lower()
    if not category:
        category = "saas"

    cached = cache_get_json(
        namespace=_JOURNEY_CATEGORY_BENCHMARK_CACHE_NAMESPACE,
        params={
            "simulation_id": simulation_id,
            "category": category,
            "limit": limit,
        },
        user_id=current_user.id,
    )
    if cached is not None:
        # The cache stores only the benchmark payload (no simulation
        # envelope), so the envelope is rebuilt from request context. A
        # payload that no longer fits the response schema (e.g. written by
        # an older version or corrupted in Redis) falls back to a fresh
        # computation instead of turning into a 500.
        try:
            return JourneyCategoryBenchmarkOut(
                simulation_id=sim.id,
                project_id=sim.project_id,
                category=category,
                **cached,
            )
        except (TypeError, ValidationError):
            logger.warning(
                "journey-category-benchmark: discarding invalid cached "
                "payload for simulation %s",
                simulation_id,  # codeql[py/log-injection]: FastAPI coerces the path param to int before the handler
            )

    rows = (
        db.query(Simulation.id, Simulation.results_json)
        .filter(
            Simulation.id != simulation_id,
            Simulation.status == "COMPLETED",
            Simulation.results_json["product_type_detected"].astext == category,
            text("results_json ? 'per_cluster_matrices'"),
        )
        .order_by(Simulation.created_at.desc())
        .limit(limit)
        .all()
    )

    cohort_summaries: list[dict[str, Any]] = []
    skipped_without_journey_data = 0
    for row in rows:
        row_results = row.results_json if isinstance(row.results_json, dict) else {}
        summary = summarise_journey_matrices(
            row_results.get("per_cluster_matrices"),
            row_results.get("cluster_weights"),
        )
        if summary is None:
            skipped_without_journey_data += 1
            continue
        cohort_summaries.append(summary)

    payload = build_journey_benchmark(
        current_payload,
        cohort_summaries,
        scope="category",
        category=category,
    )
    payload["meta"] = {
        **payload["meta"],
        "raw_completed_count": len(rows),
        "skipped_without_journey_data": skipped_without_journey_data,
        "sample_limit": limit,
    }
    cache_set_json(
        namespace=_JOURNEY_CATEGORY_BENCHMARK_CACHE_NAMESPACE,
        params={
            "simulation_id": simulation_id,
            "category": category,
            "limit": limit,
        },
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_JOURNEY_CATEGORY_BENCHMARK_CACHE_TTL_S,
    )
    return JourneyCategoryBenchmarkOut(
        simulation_id=sim.id,
        project_id=sim.project_id,
        category=category,
        **payload,
    )


@router.get(
    "/{simulation_id}/journey/benchmark/export",
    response_class=StreamingResponse,
    summary=(
        "Export a journey benchmark (portfolio or category) as CSV "
        "(or JSON with ?format=json)"
    ),
    responses=_JSON_200,
    # Both benchmark scopes scan completed simulations; cap path-spam at
    # 20/min/IP so a runaway dashboard script can't drive repeated scans.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def export_simulation_journey_benchmark(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "benchmark payload. Unsupported values return a 400 response."
        ),
    ),
    scope: str = Query(
        default="portfolio",
        max_length=16,
        description=(
            "Benchmark scope. ``portfolio`` (default) compares against "
            "the founder's other completed simulations; ``category`` "
            "compares against the latest same-category simulations "
            "platform-wide. Unsupported values return a 400 response."
        ),
    ),
    limit: int = Query(
        default=200,
        ge=10,
        le=1000,
        description=(
            "Maximum number of same-category completed simulations to "
            "include when ``scope=category``, newest first."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download a journey benchmark in CSV (default) or JSON form.

    Delegates to the same portfolio/category benchmark builders as the JSON
    endpoints, so the exported comparison can never disagree with what the
    API returns. The CSV mirrors the current funnel summary, cohort
    distribution, per-stage leak comparison, and insights in one
    spreadsheet. Pure post-hoc analytics — no Celery, no LLM, no DB writes.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv' or "
                "'json'"
            ),
        )

    scope_value = (scope or "portfolio").strip().lower()
    if scope_value not in {"portfolio", "category"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported benchmark scope {scope!r}; expected "
                "'portfolio' or 'category'"
            ),
        )

    if scope_value == "category":
        benchmark = get_simulation_journey_category_benchmark(
            simulation_id=simulation_id,
            limit=limit,
            db=db,
            current_user=current_user,
        )
    else:
        benchmark = get_simulation_journey_benchmark(
            simulation_id=simulation_id,
            db=db,
            current_user=current_user,
        )

    payload = benchmark.model_dump()
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "simulation_id": simulation_id,
        "project_id": benchmark.project_id,
        "scope": scope_value,
        "category": payload.get("category"),
        "format_version": JOURNEY_BENCHMARK_FORMAT_VERSION,
    }

    if fmt == "json":
        text = journey_benchmark_to_json(payload, metadata=metadata)
        body = text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="journey-benchmark.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = journey_benchmark_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="journey-benchmark.csv"'
            ),
            "Content-Length": str(len(body)),
        },
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
    "/{simulation_id}/cluster-run-summaries/export",
    response_class=StreamingResponse,
    summary=(
        "Export a simulation's per-cluster run summaries (agents, "
        "conversion, drop triggers, architect scores) as CSV or JSON"
    ),
    # Read-rare calibration/observability export; cap polling so a
    # dashboard loop can't drive repeated JSONB reads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_cluster_run_summaries(
    simulation_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "cluster-run-summary payload. Unsupported values return "
            "a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download a completed simulation's per-cluster run summaries.

    Unlike the main simulation export (which reconstructs cluster rows from
    ``results_json``), this endpoint reads the persisted
    ``cluster_run_summaries`` audit rows: agents assigned/converted,
    conversion rate, funnel drop-state distribution, mean drop state,
    primary drop trigger, architect scores, per-cluster signal quality,
    claim-confidence distribution and product type. These are the rows the
    calibration layer consumes, so the export is the transparency surface
    for "why did this cluster convert the way it did?".

    ``format=csv`` returns a metadata block, a compact summary section and
    one row per cluster with JSONB columns rendered as compact JSON strings;
    ``format=json`` returns the raw nested payload for BI pipelines.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

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
                f"Simulation is {sim.status} — cluster-run-summary export "
                "requires completed results."
            ),
        )

    summary_rows = (
        db.query(ClusterRunSummary)
        .filter(ClusterRunSummary.simulation_id == sim.id)
        .order_by(ClusterRunSummary.cluster_id.asc())
        .all()
    )

    cluster_names = {
        cluster_id: cluster.name for cluster_id, cluster in _clusters_map.items()
    }
    export = build_cluster_run_summary_export(
        summary_rows,
        simulation_id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        cluster_names=cluster_names,
        created_at=sim.created_at,
    )

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "simulation_id": simulation_id,
        "project_id": sim.project_id,
    }

    if fmt == "json":
        body = cluster_run_summary_to_json(
            export,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="cluster-run-summaries-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    body = cluster_run_summary_to_csv(
        export,
        metadata=metadata,
    ).encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="cluster-run-summaries-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
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


@router.get(
    "/{simulation_id}/findings-count/export",
    summary="Export one simulation's findings count as CSV or JSON",
    response_class=StreamingResponse,
)
def get_findings_count_export(
    simulation_id: int,
    format: Literal["csv", "json"] = Query(
        default="csv",
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "findings-count row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export a single simulation's domain-findings count as CSV or JSON."""
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
                f"Simulation is {sim.status} — findings-count export requires "
                "completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Simulation completed but results_json is empty.",
        )

    findings = extract_findings(sim.results_json)
    count = len(findings)
    row = {"simulation_id": simulation_id, "findings_count": count}
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
    }

    if format == "json":
        json_text = json.dumps(
            {
                "metadata": metadata,
                "simulation_id": simulation_id,
                "project_id": sim.project_id,
                "findings_count": count,
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
                    f'attachment; filename="findings-count-{simulation_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = findings_count_to_csv(row, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="findings-count-{simulation_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )
