import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.claude_client import claude_call_with_fallback
from app.core.intake_processor import adjust_assumption_confidence
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
from app.core.sanitiser import sanitise_assumption, sanitise_description, sanitise_text
from app.core.prompts import (
    ASSUMPTION_EXTRACTION_PROMPT,
    COMPETITIVE_ANALYSIS_PROMPT,
    INTERVENTION_PROMPT,
    PREMORTEM_PROMPT,
    PROTOTYPE_GENERATION_PROMPT,
)
from app.models.assumption import Assumption
from app.models.assumption_evidence import AssumptionEvidence
from app.models.decision import Decision
from app.models.environment import Environment
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.prototype import Prototype
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.assumption import (
    AssumptionDigestOut,
    AssumptionExtractRequest,
    AssumptionListResponse,
    AssumptionOut,
)
from app.schemas.competitive import (
    CompetitiveAnalysisOut,
    CompetitiveAnalysisRequest,
    Competitor,
    GapAnalysis,
    MarketMap,
    VALID_POSITIONS,
)
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentOut,
    ManualParams,
    SCENARIO_PRESETS,
)
from app.schemas.intervention import Intervention, InterventionOut, InterventionRequest
from app.schemas.premortem import FailureMode, PremortemOut, PremortemRequest
from app.schemas.project import (
    ActivityFeedOut,
    AdoptionMilestonesOut,
    BriefAssistRequest,
    BriefSave,
    ClusterCohortDriftOut,
    ConvergenceCheckOut,
    InterventionDigestOut,
    LatestSnapshotOut,
    NextBestActionOut,
    NextBestActionSource,
    PremortemDigestOut,
    ProjectExportOut,
    StaleCheckOut,
    ProjectDuplicateIn,
    ProjectDuplicateOut,
    ProjectHealthOut,
    ProjectListResponse,
    ProjectOut,
    ProjectPatch,
    ProjectSearchListResponse,
    RecommendationsDigestOut,
    ProjectTagBulkDeleteOut,
    ProjectTagRenameIn,
    ProjectTagRenameOut,
    ProjectTagsOut,
    ProjectTagsPatch,
    StatusBannerOut,
    ConfidenceExplainerOut,
    ProjectCoverageGapsOut,
)
from app.schemas.project_comparison import (
    ProjectCompareRequest,
    ProjectComparisonOut,
)
from app.schemas.prototype import FunnelEdge, FunnelGraph, FunnelNode, PrototypeOut
from app.schemas.stress_test import (
    AssumptionStressResult,
    StressTestOut,
    StressTestStatusOut,
)
from app.schemas.accountability import (
    FindingsListOut,
    FindingsSummaryOut,
    VALID_SEVERITIES,
)
from app.schemas.reweighting import ReweightingPreviewOut
from app.schemas.simulation_trend import SimulationTrendOut
from app.simulation.project_simulations_export import simulations_to_csv
from app.simulation.assumptions_export import assumptions_to_csv
from app.simulation.evidence_export import evidence_to_csv
from app.simulation.prototypes_export import prototypes_to_csv
from app.simulation.premortem_export import premortem_to_csv
from app.simulation.interventions_export import interventions_to_csv
from app.simulation.competitive_export import competitors_to_csv
from app.simulation.mvp_features_export import features_to_csv
from app.simulation.brief_export import brief_to_csv
from app.simulation.tags_export import tags_to_csv
from app.simulation.readings_export import readings_payload, readings_to_csv
from app.simulation.precis_export import precis_to_csv
from app.simulation.project_meta_export import project_meta_to_csv
from app.simulation.landing_export import landing_to_csv
from app.simulation.environment_export import environment_to_csv
from app.simulation.description_export import description_to_csv
from app.simulation.tag_suggestions import suggest_tags
from app.simulation.dossier_axis_export import dossier_axis_to_csv
from app.simulation.similar_projects import find_similar_projects
from app.simulation.intake_mode_export import intake_mode_to_csv
from app.simulation.accountability_summary import (
    DEFAULT_LIMIT as _FINDINGS_DEFAULT_LIMIT,
    MAX_LIMIT as _FINDINGS_MAX_LIMIT,
    build_findings_summary as _build_findings_summary,
    filter_findings as _filter_findings,
)
from app.simulation.reweighting_preview import (
    summarise_rule_bundle as _summarise_rule_bundle,
)
from app.simulation.simulation_trend import (
    build_simulation_trend as _build_simulation_trend,
)
from app.api.v1.common import get_owned_project
from app.api.v1.users import (
    _USER_INSIGHTS_CACHE_NAMESPACE,
    _USER_TAG_TAXONOMY_CACHE_NAMESPACE,
)
from app.core.utils import extract_json_from_markdown
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.competitive_software import CompetitiveSoftwareAnalyser
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.simulation.project_duplicate import duplicate_project_payload
from app.simulation.project_search import build_search_filters
from app.simulation.project_tags import (
    normalise_tags,
    remove_tag_from_list,
    rename_tag_in_list,
)
from app.simulation.scored_assumption import score_assumptions, signal_quality_tier
from app.simulation.activity_feed import build_activity_feed
from app.simulation.adoption_milestones import (
    build_adoption_milestones,
)
from app.simulation.assumption_digest import build_assumption_digest
from app.simulation.coverage_gaps import build_coverage_gaps
from app.simulation.coverage_gaps_export import (
    coverage_gaps_to_csv,
    coverage_gaps_to_json,
)
from app.simulation.project_health_export import (
    project_health_to_csv,
    project_health_to_json,
)
from app.simulation.recommendations_export import (
    recommendations_to_csv,
    recommendations_to_json,
)
from app.simulation.confidence_explainer import (
    build_confidence_explainer,
)
from app.simulation.cluster_cohort_drift import (
    compute_cluster_cohort_drift,
)
from app.simulation.convergence_check import build_convergence_check
from app.simulation.intervention_digest import (
    build_intervention_digest,
)
from app.simulation.latest_snapshot import build_latest_snapshot
from app.simulation.next_best_action import build_next_best_action
from app.simulation.premortem_digest import build_premortem_digest
from app.simulation.project_comparison import (
    build_project_comparison,
    normalise_confidence_score,
)
from app.simulation.project_export import build_project_export
from app.simulation.project_health import build_project_health
from app.simulation.recommendations_digest import (
    build_recommendations_digest,
)
from app.simulation.stale_check import build_stale_check
from app.simulation.status_banner import build_status_banner
from app.tasks.simulation_tasks import run_full_simulation
from app.tasks.stress_test_tasks import run_assumption_stress_test

router = APIRouter(prefix="/projects", tags=["projects"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

_comp_software_analyser = CompetitiveSoftwareAnalyser()
_conductor = Conductor()

# The "what should I do right now?" CTA lives here.
# 60s TTL absorbs dashboard polling; sim creation,
# decision creation, and outcome submission bust it
# so the answer reflects the latest state.
_NEXT_ACTION_CACHE_TTL_S: int = 60
_NEXT_ACTION_CACHE_NAMESPACE: str = "project-next-action"

# The timeline ("what just happened?") tile. Events
# mostly arrive in bursts (sim completes, decision
# completes) so a 30s TTL is enough to absorb dashboard
# polling without making a recent completion feel stale.
_ACTIVITY_FEED_CACHE_TTL_S: int = 30
_ACTIVITY_FEED_CACHE_NAMESPACE: str = "project-activity-feed"

# The assumption digest ("what does TheCee assume?").
# Assumptions are extracted infrequently (per brief
# update) so a longer 5-minute TTL is appropriate.
_ASSUMPTION_DIGEST_CACHE_TTL_S: int = 300
_ASSUMPTION_DIGEST_CACHE_NAMESPACE: str = "project-assumption-digest"

# The convergence check — predictions are stable enough
# that a 2-min TTL is plenty.
_CONVERGENCE_CHECK_CACHE_TTL_S: int = 120
_CONVERGENCE_CHECK_CACHE_NAMESPACE: str = "project-convergence"

# Intervention digest ("what should I change next?").
# 5-min TTL — interventions are generated infrequently
# (per analysis run) so longer staleness is fine.
_INTERVENTION_DIGEST_CACHE_TTL_S: int = 300
_INTERVENTION_DIGEST_CACHE_NAMESPACE: str = "project-intervention-digest"

# Per-project health score — recomputed on every
# significant project event; short TTL is fine.
_PROJECT_HEALTH_CACHE_TTL_S: int = 60
_PROJECT_HEALTH_CACHE_NAMESPACE: str = "project-health"

# Premortem digest ("what could go wrong?"). 5-min TTL:
# premortem is generated once per project and rarely
# regenerated.
_PREMORTEM_DIGEST_CACHE_TTL_S: int = 300
_PREMORTEM_DIGEST_CACHE_NAMESPACE: str = "project-premortem-digest"

# Recommendations digest - composed from premortem +
# intervention digests. 5-min TTL (both source digests
# are cached similarly).
_RECOMMENDATIONS_DIGEST_CACHE_TTL_S: int = 300
_RECOMMENDATIONS_DIGEST_CACHE_NAMESPACE: str = (
    "project-recommendations-digest"
)

# Adoption milestones ("have you done the basics?").
# Mostly stable, but every project write can flip a
# milestone - 60s TTL absorbs dashboard polling.
_ADOPTION_MILESTONES_CACHE_TTL_S: int = 60
_ADOPTION_MILESTONES_CACHE_NAMESPACE: str = (
    "project-adoption-milestones"
)

# Status banner - one-liner project health string.
# 60s TTL: 3 cheap queries in the route.
_STATUS_BANNER_CACHE_TTL_S: int = 60
_STATUS_BANNER_CACHE_NAMESPACE: str = "project-status-banner"

# Confidence explainer - "why is my confidence X?" tile.
# 60s TTL: 4 cheap queries in the route, but the
# dashboard's project-detail page refreshes often.
_CONFIDENCE_EXPLAINER_CACHE_TTL_S: int = 60
_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE: str = (
    "project-confidence-explainer"
)

# Project export (full bundle: brief + assumptions +
# sims + decisions + outcomes + premortem + interventions).
# Read-rare (manual export / handoff), but each query is
# non-trivial - 60s TTL bounds worst-case latency.
_PROJECT_EXPORT_CACHE_TTL_S: int = 60
_PROJECT_EXPORT_CACHE_NAMESPACE: str = (
    "project-export"
)

# Stale-check (data freshness lens). 60s TTL - the
# staleness thresholds are in days so most staleness
# flips don't need sub-minute precision.
_STALE_CHECK_CACHE_TTL_S: int = 60
_STALE_CHECK_CACHE_NAMESPACE: str = "project-stale-check"

# Latest snapshot (focused current-state view).
# 60s TTL: per-project, fast - dashboard's project
# header refreshes often but each source's "latest"
# only mutates on the same write paths as other tiles.
_LATEST_SNAPSHOT_CACHE_TTL_S: int = 60
_LATEST_SNAPSHOT_CACHE_NAMESPACE: str = (
    "project-latest-snapshot"
)

_SOFTWARE_PRODUCT_TYPES: frozenset[ProductType] = frozenset(
    {
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
        ProductType.ENTERPRISE_SOFTWARE,
    }
)


def _product_type_enum_from_results(raw: str | None) -> ProductType:
    s = (raw or "saas").strip().lower()
    for e in ProductType:
        if e.value == s:
            return e
    return ProductType.SAAS


def _software_benchmark_key(pt: ProductType) -> str:
    return pt.value if pt in _SOFTWARE_PRODUCT_TYPES else "saas"


def _title_fingerprint(title: str) -> str:
    """Normalised dossier title used to detect rename vs last précis mint."""
    return (title or "").strip()[:500]


def _backfill_display_precis_lazy(db: Session, project: Project) -> None:
    """One-time mint of display précis for legacy rows (fingerprint unset)."""
    if project.precis_title_fingerprint is not None:
        return
    try:
        from app.services.dossier_intelligence import generate_precis

        line = generate_precis(project.title, project.description)
        if line:
            project.precis = line
    except Exception:
        pass
    project.precis_title_fingerprint = _title_fingerprint(project.title)
    db.add(project)
    db.commit()
    db.refresh(project)


def _project_comparison_row(db: Session, project: Project) -> dict[str, Any]:
    """Gather one project's comparison snapshot.

    Keeps the route thin by collecting the same metrics the dashboard
    already uses elsewhere (health, latest sim funnel, assumptions,
    outcomes, pending decisions) into a single pure-helper payload.
    """
    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project.id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    sim_confidence: float | None = None
    latest_conversion_rate: float | None = None
    critical_finding_count = 0
    primary_failure_domain: str | None = None
    product_type_detected: str | None = None
    if latest_sim is not None:
        sim_confidence = normalise_confidence_score(
            getattr(latest_sim, "confidence_score", None),
        )
        if sim_confidence is None and latest_sim.results_json:
            agg = latest_sim.results_json.get("aggregated") or {}
            sim_confidence = normalise_confidence_score(
                agg.get("confidence_score"),
            )

        results = latest_sim.results_json or {}
        latest_conversion_rate = results.get(
            "population_weighted_conversion",
            results.get("conversion_rate"),
        )
        if latest_conversion_rate is not None:
            latest_conversion_rate = float(latest_conversion_rate)
        primary_failure_domain = results.get("primary_failure_domain")
        product_type_detected = results.get("product_type_detected")
        for finding in results.get("domain_findings", []) or []:
            if isinstance(finding, dict) and (
                finding.get("severity") == "CRITICAL"
                or finding.get("level") == "CRITICAL"
            ):
                critical_finding_count += 1

    simulation_count = (
        db.query(Simulation)
        .filter(Simulation.project_id == project.id)
        .count()
    )
    assumption_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .count()
    )
    outcome_count = (
        db.query(Outcome)
        .filter(Outcome.project_id == project.id)
        .count()
    )
    has_outcome = outcome_count > 0
    pending_decision_count = (
        db.query(Decision)
        .filter(
            Decision.project_id == project.id,
            Decision.status.in_(("PENDING", "RUNNING")),
        )
        .count()
    )

    weak_link_count = 0
    high_assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
            Assumption.sensitivity.in_(("HIGH", "CRITICAL")),
        )
        .all()
    )
    if high_assumptions:
        digest = build_assumption_digest([
            {
                "id": a.id,
                "sensitivity": a.sensitivity,
                "specificity_score": getattr(a, "specificity_score", None),
                "impact_score": a.impact_score,
                "is_hidden": a.is_hidden,
            }
            for a in high_assumptions
        ])
        weak_link_count = digest["weak_link_count"]

    health_payload = build_project_health(
        sim_confidence=sim_confidence,
        critical_finding_count=critical_finding_count,
        pending_decision_count=pending_decision_count,
        weak_link_count=weak_link_count,
        has_outcome=has_outcome,
    )

    return {
        "project_id": project.id,
        "title": project.title or "",
        "status": project.status or "DRAFT",
        "simulation_count": simulation_count,
        "assumption_count": assumption_count,
        "outcome_count": outcome_count,
        "pending_decision_count": pending_decision_count,
        "critical_finding_count": critical_finding_count,
        "weak_link_count": weak_link_count,
        "latest_conversion_rate": latest_conversion_rate,
        "latest_confidence_score": sim_confidence,
        "brief_completed": bool(project.brief_completed_at),
        "primary_failure_domain": primary_failure_domain,
        "product_type_detected": product_type_detected,
        "project_health_score": health_payload["project_health_score"],
        "project_health_verdict": health_payload["verdict"],
    }


@router.post(
    "/compare",
    response_model=ProjectComparisonOut,
    summary=(
        "Compare two owned projects side-by-side (health, funnel, "
        "assumptions, outcomes, risk signals)"
    ),
    responses=_JSON_200,
    # Pure analytics — no LLM, no Celery — but the comparison fans out
    # across both projects' child rows. Cap the path at 30/min/IP so a
    # single actor can't pin the API process on repeated comparison
    # workloads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def compare_projects(
    payload: ProjectCompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectComparisonOut:
    """Side-by-side comparison of exactly two owned projects.

    Returns per-project snapshots (latest sim funnel, health score,
    assumption / outcome / pending-decision counts) plus a dimensions
    table and an overall winner verdict. Pure analytics — no Celery
    dispatch and no LLM calls.
    """
    projects: list[Project] = []
    for project_id in payload.project_ids:
        projects.append(get_owned_project(db, current_user.id, project_id))

    rows = [_project_comparison_row(db, project) for project in projects]
    return build_project_comparison(rows)


# ── THE BRIEF — founder-authored product spec ────────────────────────────


@router.get(
    "/{project_id}/brief",
    summary="Get the current brief for a dossier",
)
def get_brief(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    import json as _json

    features = []
    if project.brief_features_json:
        try:
            features = _json.loads(project.brief_features_json)
        except Exception:
            features = []
    return {
        "positioning": project.brief_positioning or "",
        "features": features,
        "hook": project.brief_hook or "",
        "completed_at": (
            project.brief_completed_at.isoformat() if project.brief_completed_at else None
        ),
    }


@router.put(
    "/{project_id}/brief",
    summary="Save brief fields for a dossier",
    # Brief writes are per-project, low-frequency. 30/min/IP
    # keeps an accidental double-click + retry storm from
    # spamming DB writes without blocking normal use.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def save_brief(
    project_id: int,
    payload: BriefSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json as _json

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    positioning = payload.positioning.strip()
    features = payload.features
    hook = payload.hook.strip()
    mark_complete = payload.mark_complete

    project.brief_positioning = positioning
    project.brief_features_json = _json.dumps(
        [str(f).strip() for f in features if str(f).strip()][:5]
    )
    project.brief_hook = hook

    if mark_complete and positioning and hook:
        project.brief_completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(project)

    features_out = []
    if project.brief_features_json:
        try:
            features_out = _json.loads(project.brief_features_json)
        except Exception:
            features_out = []

    return {
        "positioning": project.brief_positioning or "",
        "features": features_out,
        "hook": project.brief_hook or "",
        "completed_at": (
            project.brief_completed_at.isoformat() if project.brief_completed_at else None
        ),
    }


@router.post(
    "/{project_id}/brief/assist",
    summary="Get editorial assistance for a brief field",
    # LLM-backed editorial assist — cap path-spam at 10/min/IP for
    # the same reason as the other LLM routes in this module.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def assist_brief(
    project_id: int,
    payload: BriefAssistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.brief_assistance import assist

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = payload.mode
    field = payload.field
    current_value = payload.current_value

    if mode not in ("refine", "suggest", "critique"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if field not in ("positioning", "features", "hook"):
        raise HTTPException(status_code=400, detail="Invalid field")

    result = assist(
        mode=mode,
        field=field,
        dossier_title=project.title,
        dossier_description=project.description,
        current_value=current_value,
    )

    if not result:
        raise HTTPException(status_code=500, detail="Assistance generation failed")

    return result


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List the current user’s projects",
)
def list_projects(
    tag: str | None = Query(
        default=None,
        max_length=32,
        description=(
            "Filter to projects whose tag list contains this exact "
            "canonical tag (case-insensitive on input, but the "
            "stored tag is lowercase ASCII)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Project).filter(Project.user_id == current_user.id)
    if tag is not None:
        # Normalise the filter against the same contract we use for
        # writes so a query like ``?tag=Q3%20Launch`` behaves the
        # same as one matching the stored ``"q3-launch"``.
        try:
            canonical = normalise_tags([tag])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        if not canonical:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tag filter cannot be empty",
            )
        # JSONB containment: tag is in the project's tags array.
        q = q.filter(Project.tags.op("@>")([canonical[0]]))
    projects = q.order_by(Project.created_at.desc()).all()
    return ProjectListResponse(
        projects=[ProjectOut.model_validate(p) for p in projects],
        total=len(projects),
    )


# ---------------------------------------------------------------------------
# Search — multi-filter, paginated, query substring + tag-membership
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=ProjectSearchListResponse,
    summary="Search the current user's projects (q, tags, status, archived, pagination)",
)
def search_projects(
    q: str | None = Query(
        default=None,
        max_length=512,
        description=(
            "Substring search (case-insensitive) matched against "
            "title + description + précis. Multiple words are "
            "AND-matched."
        ),
    ),
    tag: list[str] | None = Query(
        default=None,
        max_length=32,
        description=(
            "Repeat to AND-filter by multiple tags. A project must "
            "carry every supplied tag to match."
        ),
    ),
    status_filter: str | None = Query(
        default=None,
        max_length=50,
        alias="status",
        description="Exact status match (DRAFT, ACTIVE, …).",
    ),
    archived: bool | None = Query(
        default=None,
        description=(
            "When omitted, archived projects are excluded. Pass "
            "``true`` to include them, ``false`` to exclude only."
        ),
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Max projects to return (1-100, default 50). The "
            "helper coerces out-of-range values to the bound."
        ),
    ),
    before_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Cursor pagination: return only projects with id < "
            "before_id. Use the smallest ``id`` from the previous "
            "page to fetch the next one."
        ),
    ),
    sort: str | None = Query(
        default=None,
        max_length=32,
        description=(
            "Sort column. Allowed: id, created_at, updated_at, "
            "title. Default: created_at."
        ),
    ),
    order: str | None = Query(
        default=None,
        max_length=4,
        description="Sort direction: asc or desc. Default: desc.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectSearchListResponse:
    try:
        filters = build_search_filters(
            q=q,
            tags=tag,
            status=status_filter,
            archived=archived,
            limit=limit,
            before_id=before_id,
            sort=sort,
            order=order,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    base = db.query(Project).filter(Project.user_id == current_user.id)

    # Archived filter — default excludes archived (the main UI's UX).
    if filters["archived"] is False:
        base = base.filter(Project.is_archived.is_(False))
    elif filters["archived"] is True:
        base = base.filter(Project.is_archived.is_(True))
    # None == no filter (both included).

    if filters["status"] is not None:
        base = base.filter(Project.status == filters["status"])

    # Tag AND-match: every requested tag must be present.
    for t in filters["tags"]:
        base = base.filter(Project.tags.op("@>")([t]))

    # q AND-match: every word must appear (case-insensitive ILIKE) in
    # at least one of the searched columns. We use a ``func.lower``
    # containment check rather than a full-text index because the
    # dataset is per-user (small) and the contract is predictable.
    for word in filters["query_words"]:
        pattern = f"%{word}%"
        base = base.filter(
            text(
                "(LOWER(title) LIKE :pat OR LOWER(description) LIKE :pat "
                "OR LOWER(COALESCE(precis, '')) LIKE :pat)"
            ).bindparams(pat=pattern)
        )

    # Cursor pagination: id < before_id. The primary sort column is
    # configurable (see ``sort`` param), but ``id`` is *always*
    # appended as a tiebreaker so the cursor pagination contract is
    # stable even when the primary column has ties.
    if filters["before_id"] is not None:
        base = base.filter(Project.id < filters["before_id"])
    sort_col = getattr(Project, filters["sort_column"])
    direction = filters["order"]
    # ``id`` always ends up second so cursor pagination stays
    # deterministic regardless of the primary sort.
    if filters["sort_column"] == "id":
        base = base.order_by(sort_col.asc() if direction == "asc" else sort_col.desc())
    else:
        primary = sort_col.asc() if direction == "asc" else sort_col.desc()
        tiebreak = Project.id.asc() if direction == "asc" else Project.id.desc()
        base = base.order_by(primary, tiebreak)

    # Fetch one extra row to compute ``has_more`` without a second
    # COUNT query.
    page_size = filters["limit"]
    rows = base.limit(page_size + 1).all()
    has_more = len(rows) > page_size
    projects = rows[:page_size]

    # Total filtered count (without pagination) — useful for the
    # "X results" footer in the UI. One extra COUNT query is cheap
    # at the per-user scale.
    total = db.query(Project).filter(Project.user_id == current_user.id)
    if filters["archived"] is False:
        total = total.filter(Project.is_archived.is_(False))
    elif filters["archived"] is True:
        total = total.filter(Project.is_archived.is_(True))
    if filters["status"] is not None:
        total = total.filter(Project.status == filters["status"])
    for t in filters["tags"]:
        total = total.filter(Project.tags.op("@>")([t]))
    for word in filters["query_words"]:
        pattern = f"%{word}%"
        total = total.filter(
            text(
                "(LOWER(title) LIKE :pat OR LOWER(description) LIKE :pat "
                "OR LOWER(COALESCE(precis, '')) LIKE :pat)"
            ).bindparams(pat=pattern)
        )
    total_count = total.count()

    next_cursor = projects[-1].id if (has_more and projects) else None

    return ProjectSearchListResponse(
        projects=[ProjectOut.model_validate(p) for p in projects],
        total=total_count,
        has_more=has_more,
        next_before_id=next_cursor,
    )



# ---------------------------------------------------------------------------
# Tags — set, clear, filter
# ---------------------------------------------------------------------------


@router.put(
    "/{project_id}/tags",
    response_model=ProjectTagsOut,
    summary="Replace the project's tag set (empty list clears all)",
    # DB write — 20/min/IP so the friendly UI works but a probe loop
    # can't blast tag mutations across every project it owns.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def put_project_tags(
    project_id: int,
    payload: ProjectTagsPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTagsOut:
    project = get_owned_project(db, current_user.id, project_id)
    try:
        new_tags = normalise_tags(payload.tags)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    project.tags = new_tags
    db.add(project)
    db.commit()
    db.refresh(project)
    # /me/tag-taxonomy buckets by tag name + project count.
    # The set of tags + per-tag counts just changed.
    cache_invalidate(
        namespace=_USER_TAG_TAXONOMY_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    return ProjectTagsOut(id=project.id, tags=list(project.tags or []))


@router.get(
    "/{project_id}/tag-suggestions",
    summary="Suggest simple keyword tags from the project title/description",
    responses=_JSON_200,
)
def get_tag_suggestions(
    project_id: int,
    max_tags: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Return a small heuristic tag-suggestion list for the project."""
    project = get_owned_project(db, current_user.id, project_id)
    existing = set(project.tags or [])
    tags = [
        tag
        for tag in suggest_tags(project.title, project.description, max_tags=max_tags)
        if tag not in existing
    ]
    return {
        "project_id": project.id,
        "tags": tags,
    }


@router.get(
    "/{project_id}/similar-projects",
    summary="Find other owned projects sharing tags with this project",
    responses=_JSON_200,
)
def get_similar_projects(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Return the current user's other projects that share tags."""
    project = get_owned_project(db, current_user.id, project_id)
    candidates = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    candidate_rows = [
        {
            "id": candidate.id,
            "title": candidate.title,
            "tags": list(candidate.tags or []),
        }
        for candidate in candidates
    ]
    project_row = {
        "id": project.id,
        "title": project.title,
        "tags": list(project.tags or []),
    }
    return {
        "project_id": project.id,
        "similar": find_similar_projects(project_row, candidate_rows),
    }


@router.delete(
    "/{project_id}/tags/{tag}",
    response_model=ProjectTagsOut,
    summary="Remove a single tag from a project (no-op if absent)",
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def delete_project_tag(
    project_id: int,
    tag: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTagsOut:
    project = get_owned_project(db, current_user.id, project_id)
    try:
        canonical_list = normalise_tags([tag])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    target = canonical_list[0]
    current_tags = list(project.tags or [])
    if target in current_tags:
        current_tags = [t for t in current_tags if t != target]
        project.tags = current_tags
        db.add(project)
        db.commit()
        db.refresh(project)
        # /me/tag-taxonomy buckets by tag name + project
        # count. The set of tags + per-tag counts just
        # changed (target tag no longer on this project).
        cache_invalidate(
            namespace=_USER_TAG_TAXONOMY_CACHE_NAMESPACE,
            user_id=current_user.id,
        )
    return ProjectTagsOut(id=project.id, tags=list(project.tags or []))


@router.get(
    "/tags",
    response_model=list[str],
    summary="List every distinct tag in use across the current user’s projects",
)
def list_user_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """Return the union of all tags across the user's projects as a
    canonical, sorted list. Powers the tag-filter dropdown in the UI
    without having to ship the full project list with every request."""
    rows = (
        db.query(Project.tags)
        .filter(Project.user_id == current_user.id)
        .all()
    )
    seen: set[str] = set()
    for (tags,) in rows:
        if not tags:
            continue
        for t in tags:
            if isinstance(t, str) and t:
                seen.add(t)
    return sorted(seen)


# Bulk operations on the user's tag namespace — implemented as
# in-process Python loops over the user's projects rather than a
# single JSONB UPDATE. The dataset is per-user (small, capped by
# subscription tier) and the loop makes the rename/delete idempotent
# + observable through the same ORM path as the per-project routes.
# If a future user has thousands of projects, replace with a single
# UPDATE … WHERE tags @> '["old"]' ::jsonb.


@router.put(
    "/tags/{old_tag}",
    response_model=ProjectTagRenameOut,
    summary="Rename a tag across every project the user owns",
    # Lower cap than per-project writes — bulk renames are bursty
    # one-off operations, not steady-state UI traffic.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def rename_user_tag(
    old_tag: str,
    payload: ProjectTagRenameIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTagRenameOut:
    try:
        canonical_old = normalise_tags([old_tag])
        canonical_new = normalise_tags([payload.new])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    old = canonical_old[0]
    new = canonical_new[0]
    if old == new:
        # No-op rename — return 0 updates rather than 400 so the UI
        # can treat "rename to same" as a definitional success.
        return ProjectTagRenameOut(old=old, new=new, projects_updated=0)

    rows = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .filter(Project.tags.op("@>")([old]))
        .all()
    )
    updated = 0
    for project in rows:
        try:
            new_tags = rename_tag_in_list(list(project.tags or []), old, new)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        project.tags = new_tags
        db.add(project)
        updated += 1
    if updated:
        db.commit()

    return ProjectTagRenameOut(old=old, new=new, projects_updated=updated)


@router.delete(
    "/tags/{old_tag}",
    response_model=ProjectTagBulkDeleteOut,
    summary="Delete a tag from every project the user owns",
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def delete_user_tag(
    old_tag: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTagBulkDeleteOut:
    try:
        canonical = normalise_tags([old_tag])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    target = canonical[0]
    rows = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .filter(Project.tags.op("@>")([target]))
        .all()
    )
    updated = 0
    for project in rows:
        project.tags = remove_tag_from_list(list(project.tags or []), target)
        db.add(project)
        updated += 1
    if updated:
        db.commit()

    return ProjectTagBulkDeleteOut(tag=target, projects_updated=updated)


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update dossier title or description",
    # DB write — cap path-spam at 30/min/IP for the same reason as
    # the simulations POST limit. Legitimate users re-save titles a
    # few times per session; this caps runaway scripts.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def patch_project(
    project_id: int,
    payload: ProjectPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.title is None and payload.description is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide title and/or description to update",
        )
    project = get_owned_project(db, current_user.id, project_id)

    title_changed = False
    if payload.title is not None:
        new_title = sanitise_text(payload.title.strip(), max_length=500)
        if not new_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Title cannot be empty",
            )
        if new_title != project.title:
            project.title = new_title
            title_changed = True

    if payload.description is not None:
        project.description = sanitise_description(payload.description)

    if title_changed:
        try:
            from app.services.dossier_intelligence import generate_precis

            line = generate_precis(project.title, project.description)
            if line:
                project.precis = line
        except Exception as exc:
            logger.warning("precis refresh on dossier rename failed: %s", exc)
        project.precis_title_fingerprint = _title_fingerprint(project.title)

    # /me/dashboard, /me/projects-by-status,
    # /me/projects-needing-attention, /me/most-active-project,
    # /me/last-touched-project, /me/portfolio-health-snapshot
    # all reflect either the project title (on title change)
    # or the per-project health score (on description change,
    # because the per-project health endpoint reads the
    # current description). Either field change leaves them
    # stale for up to each tile's TTL.
    if title_changed or payload.description is not None:
        from app.api.v1.users import (
            _USER_DASHBOARD_CACHE_NAMESPACE,
            _USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
            _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
            _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
            _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
            _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        )
        for _ns in (
            _USER_DASHBOARD_CACHE_NAMESPACE,
            _USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
            _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
            _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
            _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
            _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        ):
            cache_invalidate(namespace=_ns, user_id=current_user.id)

    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.patch(
    "/{project_id}/archive",
    response_model=ProjectOut,
    summary="Move dossier to the archive",
    # DB write — cap path-spam at 20/min/IP.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def archive_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    project.is_archived = True
    db.add(project)
    db.commit()
    db.refresh(project)
    # /me/insights (executive summary) reflects the user's
    # active project count + status mix. Archive flips
    # the project's is_archived → active count drops.
    cache_invalidate(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    return ProjectOut.model_validate(project)


@router.patch(
    "/{project_id}/unarchive",
    response_model=ProjectOut,
    summary="Restore dossier from the archive",
    # DB write — cap path-spam at 20/min/IP.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def unarchive_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    project.is_archived = False
    db.add(project)
    db.commit()
    db.refresh(project)
    # /me/insights reflects active project count + status.
    # Unarchive flips the project's is_archived → active
    # count goes up.
    cache_invalidate(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    return ProjectOut.model_validate(project)


@router.post(
    "/{project_id}/duplicate",
    response_model=ProjectDuplicateOut,
    status_code=201,
    summary="Clone a project (and its environment) to a new draft",
    # DB write — cap path-spam at 20/min/IP. Tier enforcement still
    # applies via the per-user project-count quota further downstream.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def duplicate_project(
    project_id: int,
    payload: ProjectDuplicateIn | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clone ``project_id`` (and its environment) to a new draft owned by
    the same user. The new project starts in ``DRAFT`` status with no
    brief, no assumptions. By default, simulation history is **not**
    copied — set ``include_simulations=true`` to snapshot COMPLETED
    simulations into the duplicate (useful for branching off a known
    baseline).

    Set ``dry_run=true`` to preview the duplicate without writing.
    """
    source = get_owned_project(db, current_user.id, project_id)
    env = (
        db.query(Environment)
        .filter(Environment.project_id == source.id)
        .first()
    )

    payload = payload or ProjectDuplicateIn()
    built = duplicate_project_payload(
        project={
            "title": source.title,
            "description": source.description,
            "precis": source.precis,
            "readings_json": source.readings_json,
        },
        environment=(
            {
                "mode": env.mode,
                "consumer_volume": env.consumer_volume,
                "growth_rate_per_month": env.growth_rate_per_month,
                "average_order_value": env.average_order_value,
                "price_sensitivity": env.price_sensitivity,
                "market_maturity": env.market_maturity,
                "scenario_type": env.scenario_type,
                "manual_params_json": env.manual_params_json,
                "trend_data_json": env.trend_data_json,
            }
            if env is not None
            else None
        ),
        new_title=payload.new_title,
    )

    # Dry run — return the planned payload without persisting.
    if payload.dry_run:
        preview = Project(
            id=0,  # placeholder; client should treat as "would be created"
            user_id=current_user.id,
            title=built["project"]["title"],
            description=built["project"]["description"],
            precis=built["project"]["precis"],
            readings_json=built["project"]["readings_json"],
            status="DRAFT",
            tags=built["project"].get("tags") or [],
        )
        return ProjectDuplicateOut(
            project=ProjectOut.model_validate(preview),
            source_project_id=source.id,
            simulations_copied=0,
            environment_copied=built["environment"] is not None,
            dry_run=True,
        )

    new_project = Project(
        user_id=current_user.id,
        title=built["project"]["title"],
        description=built["project"]["description"],
        precis=built["project"]["precis"],
        readings_json=built["project"]["readings_json"],
        status="DRAFT",
        tags=built["project"].get("tags") or [],
    )
    db.add(new_project)
    db.flush()  # populate new_project.id without committing

    if built["environment"] is not None:
        new_env = Environment(
            project_id=new_project.id,
            mode=built["environment"]["mode"],
            consumer_volume=built["environment"]["consumer_volume"],
            growth_rate_per_month=built["environment"]["growth_rate_per_month"],
            average_order_value=built["environment"]["average_order_value"],
            price_sensitivity=built["environment"]["price_sensitivity"],
            market_maturity=built["environment"]["market_maturity"],
            scenario_type=built["environment"]["scenario_type"],
            manual_params_json=built["environment"]["manual_params_json"],
            trend_data_json=built["environment"]["trend_data_json"],
        )
        db.add(new_env)

    # Optional: snapshot COMPLETED simulations from the source.
    simulations_copied = 0
    if payload.include_simulations:
        completed = (
            db.query(Simulation)
            .filter(
                Simulation.project_id == source.id,
                Simulation.status == "COMPLETED",
            )
            .order_by(Simulation.created_at.asc())
            .all()
        )
        for sim in completed:
            db.add(
                Simulation(
                    project_id=new_project.id,
                    environment_id=None,  # don't retarget to the new env
                    status="COMPLETED",
                    consumer_volume=sim.consumer_volume,
                    results_json=sim.results_json,
                    confidence_score=sim.confidence_score,
                    signal_quality=sim.signal_quality,
                    claim_confidence_distribution=sim.claim_confidence_distribution,
                )
            )
            simulations_copied += 1

    db.commit()
    db.refresh(new_project)

    logger.info(
        "[Project] Duplicated — source_id=%s new_id=%s user_id=%s sims=%s",
        source.id,
        new_project.id,
        current_user.id,
        simulations_copied,
    )
    # /me/insights reflects active project count + recent
    # activity. duplicate_project just added a new project,
    # so the cached summary would otherwise be stale.
    cache_invalidate(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    return ProjectDuplicateOut(
        project=ProjectOut.model_validate(new_project),
        source_project_id=source.id,
        simulations_copied=simulations_copied,
        environment_copied=built["environment"] is not None,
        dry_run=False,
    )


@router.get(
    "/{project_id}/clusters",
    summary="Cluster-level conversion from the latest completed simulation",
    responses=_JSON_200,
)
def get_project_clusters(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not latest_sim or not latest_sim.results_json:
        return {"clusters": [], "message": "No completed simulation found"}

    breakdown = latest_sim.results_json.get("cluster_breakdown", {})
    _clusters = {c.cluster_id: c for c in ClusterRegistry().all_clusters()}
    clusters_out = [
        {
            "cluster_id": cid,
            "name": _clusters[cid].name if cid in _clusters else cid,
            "conversion_rate": round(float(cr), 4),
            "population_fraction": round(_clusters[cid].population_weight, 4)
            if cid in _clusters
            else 0.0,
            "dominant_behavior": _clusters[cid].dominant_behavior_pattern
            if cid in _clusters
            else "",
            "known_failure_modes": _clusters[cid].known_failure_modes if cid in _clusters else [],
            "demographic_profile": _clusters[cid].demographic_profile if cid in _clusters else {},
        }
        for cid, cr in sorted(breakdown.items(), key=lambda x: -x[1])
    ]
    return {"clusters": clusters_out, "simulation_id": latest_sim.id}


@router.get(
    "/{project_id}/reweighting-preview",
    response_model=ReweightingPreviewOut,
    summary="Preview the cluster reweighting engine would apply for this project",
    responses=_JSON_200,
)
def get_reweighting_preview(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the rule bundle the ClusterReweightingEngine would apply for
    the project's environment params, the suppressed + amplified clusters,
    and the top-/bottom-weighted clusters by final weight. Pure preview —
    no DB writes, no Celery dispatch.
    """
    from app.simulation.cluster_reweighting import (
        ClusterReweightingEngine,
        REWEIGHTING_RULES,
    )

    project = get_owned_project(db, current_user.id, project_id)
    environment = (
        db.query(Environment).filter(Environment.project_id == project_id).first()
    )

    aov = float((environment.average_order_value if environment else 0.0) or 0.0)
    geo = str((environment.geography if environment else "") or "")
    segment = str((environment.target_segment if environment else "") or "")
    age = str((environment.age_target if environment else "") or "")
    raw_pt = (
        project.product_type
        or (getattr(environment, "scenario_type", None) if environment else None)
        or "saas"
    )
    pt = _product_type_enum_from_results(raw_pt)

    engine = ClusterReweightingEngine()
    final_weights = engine.compute_weights(
        product_type=pt, aov=aov, geography=geo, segment=segment, age_target=age
    )

    # Baseline weights (no rule applied) for the weight_sum check.
    registry = ClusterRegistry()
    cluster_names = {c.cluster_id: c.name for c in registry.all_clusters()}
    baseline_weights = {c.cluster_id: c.population_weight for c in registry.all_clusters()}

    # Identify which rule key the engine selected (it may fall back to DEFAULT).
    selected_rule = engine._select_rule_bundle(
        product_type=pt, aov=aov, geography=geo, segment=segment, age_target=age
    )
    rules = REWEIGHTING_RULES.get(selected_rule, REWEIGHTING_RULES["DEFAULT"])

    preview = _summarise_rule_bundle(
        rule_key=selected_rule,
        rules={"suppress": rules.suppress, "amplify": dict(rules.amplify)},
        final_weights=final_weights,
        baseline_weights=baseline_weights,
        cluster_names=cluster_names,
    )

    return ReweightingPreviewOut(
        project_id=project_id,
        product_type=pt.value,
        aov=aov,
        geography=geo or None,
        segment=segment or None,
        age_target=age or None,
        **preview,
    )


@router.get(
    "/{project_id}/domain-findings",
    response_model=FindingsListOut,
    summary="Architect domain findings from the latest completed run (filterable)",
    responses=_JSON_200,
)
def get_domain_findings(
    project_id: int,
    severity: str | None = Query(
        default=None,
        description="Filter by severity: CRITICAL | WARNING | INFO",
    ),
    architect: str | None = Query(
        default=None,
        description="Case-insensitive substring match on architect name",
    ),
    metric: str | None = Query(
        default=None,
        description="Exact match on the metric_affected field",
    ),
    limit: int = Query(default=_FINDINGS_DEFAULT_LIMIT, ge=1, le=_FINDINGS_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    if severity is not None and severity.strip().upper() not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid severity '{severity}'. "
                f"Allowed: {sorted(VALID_SEVERITIES)}"
            ),
        )

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not latest_sim or not latest_sim.results_json:
        return FindingsListOut(
            project_id=project_id,
            simulation_id=latest_sim.id if latest_sim else None,
            primary_failure_domain="unknown",
            highest_value_cluster={},
            total=0,
            findings=[],
            filters={
                "severity": severity,
                "architect": architect,
                "metric": metric,
                "limit": limit,
                "offset": offset,
            },
        )

    results = latest_sim.results_json
    raw = results.get("domain_findings", [])
    filtered = _filter_findings(
        raw,
        severity=severity,
        architect=architect,
        metric=metric,
        limit=limit,
        offset=offset,
    )

    return FindingsListOut(
        project_id=project_id,
        simulation_id=latest_sim.id,
        primary_failure_domain=results.get("primary_failure_domain", "unknown"),
        highest_value_cluster=results.get("highest_value_cluster", {}),
        total=len(_filter_findings(raw)),  # count after filters, before pagination
        findings=filtered,
        filters={
            "severity": severity,
            "architect": architect,
            "metric": metric,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get(
    "/{project_id}/findings/summary",
    response_model=FindingsSummaryOut,
    summary="Group-by rollup of persisted domain findings (architect/cluster/metric/action)",
    responses=_JSON_200,
)
def get_findings_summary(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not latest_sim or not latest_sim.results_json:
        return FindingsSummaryOut(
            project_id=project_id,
            simulation_id=latest_sim.id if latest_sim else None,
        )

    results = latest_sim.results_json
    raw = results.get("domain_findings", [])
    summary = _build_findings_summary(raw)
    summary.project_id = project_id
    summary.simulation_id = latest_sim.id
    summary.primary_failure_domain = results.get("primary_failure_domain", "unknown")
    summary.highest_value_cluster = results.get("highest_value_cluster", {})
    return summary


@router.get(
    "/{project_id}/assumptions",
    response_model=AssumptionListResponse,
    summary="List scored assumptions for a project",
)
def get_assumptions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )
    hidden_count = sum(1 for a in assumptions if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in assumptions],
        total=len(assumptions),
        hidden_count=hidden_count,
    )


@router.get(
    "/{project_id}/assumptions/export",
    summary="Export a project's assumptions as CSV",
    response_class=StreamingResponse,
)
def export_assumptions(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "assumption rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's assumption rows."""
    get_owned_project(db, current_user.id, project_id)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )
    rows = [
        {
            "id": assumption.id,
            "project_id": assumption.project_id,
            "text": assumption.text,
            "category": assumption.category,
            "sensitivity": assumption.sensitivity,
            "impact_score": assumption.impact_score,
            "is_hidden": assumption.is_hidden,
            "created_at": assumption.created_at,
        }
        for assumption in assumptions
    ]

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "assumptions": rows,
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
                    f'attachment; filename="assumptions-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = assumptions_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="assumptions-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/evidence/export",
    summary="Export a project's assumption evidence as CSV",
    response_class=StreamingResponse,
)
def export_evidence(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "evidence rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's assumption evidence rows."""
    get_owned_project(db, current_user.id, project_id)

    evidence_rows = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project_id)
        .order_by(AssumptionEvidence.created_at.desc())
        .all()
    )
    rows = [
        {
            "id": evidence.id,
            "project_id": evidence.project_id,
            "assumption_id": evidence.assumption_id,
            "method": evidence.method,
            "result": evidence.result,
            "observed_metric": evidence.observed_metric,
            "notes": evidence.notes,
            "created_at": evidence.created_at,
        }
        for evidence in evidence_rows
    ]

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "evidence": rows,
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
                    f'attachment; filename="evidence-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = evidence_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="evidence-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/extract-assumptions",
    response_model=AssumptionListResponse,
    summary="Run Claude to extract and score assumptions",
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def extract_assumptions(
    project_id: int,
    payload: AssumptionExtractRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    raw_description = (
        payload.description
        if payload and payload.description
        else project.description
    )
    description = sanitise_description(raw_description or "")

    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Description too short to extract meaningful assumptions",
        )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": ASSUMPTION_EXTRACTION_PROMPT.format(
                        description=description
                    ),
                }
            ],
            system=(
                "You are a world-class startup mentor specializing in surfacing "
                "dangerous hidden assumptions that kill products. "
                "You ALWAYS return valid JSON only, no markdown, no explanation."
            ),
            model="claude-sonnet-4-5",
            max_tokens=2000,
            fallback_key="assumption_extraction",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()

        raw = extract_json_from_markdown(raw)
        parsed = json.loads(raw)
        assumptions_data = parsed.get("assumptions", [])

        if not isinstance(assumptions_data, list):
            raise ValueError("Claude returned unexpected format")

        prepped: list[dict] = []
        for item in assumptions_data:
            if not isinstance(item, dict):
                continue
            t = str(item.get("text", "")).strip()
            prepped.append(
                {
                    **item,
                    "text": t,
                    "assumption": t,
                    "claim_confidence": str(item.get("claim_confidence", "DESIGN_INTENT")),
                }
            )
        assumptions_data = adjust_assumption_confidence(
            prepped, project.intake_mode or "IDEA"
        )
        for a in assumptions_data:
            t = sanitise_assumption(str(a.get("text", a.get("assumption", ""))))
            a["text"] = t
            a["assumption"] = t

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned invalid JSON — retry the request",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Assumption extraction failed: {str(e)}",
        )

    db.query(Assumption).filter(Assumption.project_id == project_id).delete()
    db.commit()

    saved = []
    for item in assumptions_data:
        sensitivity = str(item.get("sensitivity", "MEDIUM")).upper()
        if sensitivity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            sensitivity = "MEDIUM"

        assumption = Assumption(
            project_id=project_id,
            text=str(item.get("text", "")).strip(),
            category=str(item.get("category", "Market")).strip(),
            sensitivity=sensitivity,
            impact_score=min(10.0, max(1.0, float(item.get("impact_score", 5.0)))),
            is_hidden=bool(item.get("is_hidden", False)),
        )
        db.add(assumption)
        saved.append(assumption)

    project.status = "ASSUMPTIONS_EXTRACTED"
    db.commit()

    for assumption in saved:
        db.refresh(assumption)

    # Score assumptions and compute signal quality for this extraction run.
    scored_list, hard_count, soft_flags, sq = score_assumptions(
        [
            {
                "id": a.id,
                "text": a.text,
                "category": a.category,
                "impact_score": a.impact_score,
                "claim_confidence": item.get("claim_confidence"),
            }
            for a, item in zip(saved, assumptions_data, strict=True)
        ]
    )

    # Build confidence distribution summary (count per tier).
    confidence_dist: dict[str, int] = {}
    for sa in scored_list:
        key = sa.claim_confidence.value
        confidence_dist[key] = confidence_dist.get(key, 0) + 1

    sq_tier = signal_quality_tier(sq)

    # Persist signal_quality on the most recent simulation for this project,
    # or update it when the next simulation is created (Step 37 task picks this up).
    # For now, write to the latest QUEUED/RUNNING simulation if one exists.
    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if latest_sim is not None:
        latest_sim.signal_quality = sq
        latest_sim.claim_confidence_distribution = confidence_dist
        db.commit()

    # Apply personal accuracy adjustment from user_claim_accuracy_profiles
    # if the user has enough history (sample_count >= 3, reliability >= 0.40).
    # This is a read-only advisory enrichment — it does not modify saved rows.
    user_reliability_note: str | None = None
    try:
        profile_rows = db.execute(
            text(
                "SELECT architect_name, ema_delta, reliability_score, sample_count "
                "FROM user_claim_accuracy_profiles "
                "WHERE user_id = :uid AND sample_count >= 3 AND reliability_score >= 0.40"
            ),
            {"uid": current_user.id},
        ).fetchall()
        if profile_rows:
            user_reliability_note = (
                f"Personal accuracy profile active: {len(profile_rows)} architects calibrated."
            )
    except Exception as _exc:
        logger.debug(
            "%s suppressed: %s",
            __name__,
            _exc,
        )

    hidden_count = sum(1 for a in saved if a.is_hidden)

    # Bust the cached assumption-digest so the next GET
    # reflects the re-extracted set rather than waiting
    # out the 5-min TTL. Also bust the per-project health
    # score — the weak-link count input changes.
    cache_invalidate(
        namespace=_ASSUMPTION_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_PROJECT_HEALTH_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    # Bust the cached /me/coverage-gaps — the covered
    # categories + sensitivity breakdown change when the
    # user's assumption set is regenerated. Also bust the
    # project-level stale-check (latest assumption
    # created_at changes).
    from app.api.v1.users import (
    _USER_COVERAGE_GAPS_CACHE_NAMESPACE,
    _USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
    _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
    _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
)
    cache_invalidate(
        namespace=_USER_COVERAGE_GAPS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in saved],
        total=len(saved),
        hidden_count=hidden_count,
        signal_quality=sq,
        signal_quality_tier=sq_tier,
        claim_confidence_distribution=confidence_dist,
        soft_contradiction_flags=soft_flags,
        message=(
            user_reliability_note or "Assumptions extracted successfully"
        ),
    )


@router.post(
    "/{project_id}/generate-prototype",
    response_model=PrototypeOut,
    summary="Generate a landing-page HTML prototype (Claude)",
    # LLM-backed prototype generation is expensive — cap path-spam at
    # 10/min/IP so a single actor can't drain LLM quota.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def generate_prototype(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    if not project.description or len(project.description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description is too short to generate a prototype",
        )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": PROTOTYPE_GENERATION_PROMPT.format(
                        description=project.description
                    ),
                }
            ],
            system=(
                "You are a world-class product designer and conversion rate expert. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Your HTML prototypes look like real funded startup products."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            fallback_key="prototype_generation",
            timeout=120,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()

        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))

        html_content = parsed.get("html_content", "")
        funnel_data = parsed.get("funnel_graph", {})

        if not html_content or len(html_content) < 100:
            raise ValueError("Generated HTML is too short or empty")

        if not funnel_data.get("nodes") or not funnel_data.get("edges"):
            raise ValueError("Funnel graph is missing nodes or edges")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — please retry",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Prototype generation failed: {str(e)}",
        )

    existing = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )

    if existing:
        existing.html_content = html_content
        existing.funnel_graph_json = json.dumps(funnel_data)
        prototype = existing
    else:
        prototype = Prototype(
            project_id=project_id,
            html_content=html_content,
            funnel_graph_json=json.dumps(funnel_data),
        )
        db.add(prototype)

    project.status = "PROTOTYPE_GENERATED"
    project.prototype_html = html_content
    project.funnel_graph_json = json.dumps(funnel_data)

    db.commit()
    db.refresh(prototype)

    try:
        funnel_graph = FunnelGraph(
            nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
            edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
        )
    except Exception:
        funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=html_content,
        funnel_graph=funnel_graph,
    )


@router.get(
    "/{project_id}/prototype",
    response_model=PrototypeOut,
    summary="Get stored HTML prototype and funnel graph",
)
def get_prototype(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    prototype = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )
    if not prototype:
        raise HTTPException(
            status_code=404,
            detail="No prototype generated yet — call POST /generate-prototype first",
        )

    funnel_graph = None
    if prototype.funnel_graph_json:
        try:
            funnel_data = json.loads(prototype.funnel_graph_json)
            funnel_graph = FunnelGraph(
                nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
                edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
            )
        except Exception:
            funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=prototype.html_content,
        funnel_graph=funnel_graph,
    )


@router.get(
    "/{project_id}/prototypes/export",
    summary="Export a project's prototypes as CSV or JSON",
    response_class=StreamingResponse,
)
def export_prototypes(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "prototype rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet or JSON export of a project's prototype rows."""
    get_owned_project(db, current_user.id, project_id)

    prototypes = (
        db.query(Prototype)
        .filter(Prototype.project_id == project_id)
        .order_by(Prototype.created_at.desc())
        .all()
    )
    rows = [
        {
            "id": prototype.id,
            "project_id": prototype.project_id,
            "html_content": prototype.html_content,
            "funnel_graph_json": prototype.funnel_graph_json,
            "created_at": prototype.created_at,
        }
        for prototype in prototypes
    ]

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "prototypes": rows,
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
                    f'attachment; filename="prototypes-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = prototypes_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="prototypes-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/premortem",
    response_model=PremortemOut,
    summary="Run premortem failure mode analysis (Claude)",
    # LLM-backed; cap path-spam at 10/min/IP.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def run_premortem(
    project_id: int,
    payload: PremortemRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short for pre-mortem analysis",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )

    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    assumptions_text = "\n".join(
        f"- [{a.sensitivity}] {a.text} (impact: {a.impact_score}/10)" for a in assumptions
    ) or "No assumptions extracted yet."

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    domain_findings_text = (
        "\n".join(
            [
                f"[{f.get('severity', 'INFO')}] {f.get('architect_name', '')} / "
                f"{f.get('cluster_name', '')}: {f.get('finding', '')} "
                f"(impact: {float(f.get('conversion_impact', 0) or 0):.3f})"
                for f in findings[:10]
            ]
        )
        if findings
        else "No domain findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": PREMORTEM_PROMPT.format(
                        domain_findings_text=domain_findings_text,
                        primary_failure_domain=primary_fd,
                        highest_value_cluster=hv_name,
                        cluster_narrative=narrative,
                    ),
                }
            ],
            system=(
                "You are an elite startup failure analyst specialising in pre-mortem analysis. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=2800,
            fallback_key="premortem",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))
        raw_modes = parsed.get("failure_modes", [])

        if not isinstance(raw_modes, list) or len(raw_modes) == 0:
            raise ValueError("Claude returned empty failure_modes list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON - retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Pre-mortem analysis failed: {str(exc)}",
        )

    failure_modes: list[FailureMode] = []
    for item in raw_modes:
        try:
            fm = FailureMode(
                title=str(item.get("title", item.get("failure_mode", "Unknown failure"))).strip(),
                probability=float(item.get("probability", 0.5)),
                severity=str(item.get("severity", "MEDIUM")),
                trigger_condition=str(item.get("trigger_condition", "")).strip(),
                linked_assumption_texts=[
                    str(a).strip()
                    for a in item.get(
                        "linked_assumption_texts", item.get("linked_assumptions", [])
                    )
                ],
                intervention=str(
                    item.get("intervention", item.get("recommended_intervention", ""))
                ).strip(),
                intervention_impact=str(
                    item.get("intervention_impact", item.get("expected_impact", ""))
                ).strip(),
                earliest_signal=str(item.get("earliest_signal", "")).strip(),
            )
            failure_modes.append(fm)
        except Exception:
            continue

    if not failure_modes:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid failure modes from Claude response",
        )

    failure_modes.sort(key=lambda f: f.probability, reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    premortem_data = {
        "failure_modes": [fm.model_dump() for fm in failure_modes],
        "generated_at": now,
        "simulation_id": latest_sim.id if latest_sim else None,
        "assumptions_count": len(assumptions),
    }

    project.premortem_json = premortem_data
    project.status = "PREMORTEM_COMPLETE"
    db.commit()

    # Bust the cached premortem-digest so the next GET
    # reflects the freshly-generated failure modes rather
    # than waiting out the 5-min TTL. Also bust the
    # recommendations-digest - it composes both premortem
    # + intervention, so it must refresh when premortem
    # mutates. Also bust adoption-milestones - premortem
    # completion flips the premortem_run milestone.
    cache_invalidate(
        namespace=_PREMORTEM_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_RECOMMENDATIONS_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=now,
    )


@router.get(
    "/{project_id}/premortem",
    response_model=PremortemOut,
    summary="Get stored premortem JSON",
)
def get_premortem(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "premortem_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No pre-mortem generated yet - call POST /premortem first",
        )

    failure_modes = [FailureMode(**fm) for fm in data.get("failure_modes", [])]
    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=data.get("generated_at", ""),
    )


@router.get(
    "/{project_id}/premortem/export",
    summary="Export a project's premortem failure modes as CSV",
    response_class=StreamingResponse,
)
def export_premortem(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "premortem rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's premortem failure modes."""
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "premortem_json", None) or {}
    rows = list(data.get("failure_modes", []) or [])

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "premortem": rows,
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
                    f'attachment; filename="premortem-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = premortem_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="premortem-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/stress-test",
    response_model=StressTestStatusOut,
    summary="Start or poll assumption stress test job",
    # Celery-backed but still costs worker time and queue slots;
    # cap path-spam at 10/min/IP.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def start_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    environment = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /environments first.",
        )

    critical_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.sensitivity.in_(["CRITICAL", "HIGH"]),
        )
        .count()
    )
    if critical_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No CRITICAL or HIGH assumptions found. Run assumption extraction first.",
        )

    task = run_assumption_stress_test.delay(project_id)
    return StressTestStatusOut(
        project_id=project_id,
        status="PENDING",
        task_id=task.id,
        result=None,
    )


@router.get(
    "/{project_id}/stress-test",
    response_model=StressTestStatusOut,
    summary="Get stress test status and result",
)
def get_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    raw = getattr(project, "stress_test_json", None)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail="No stress test run yet — call POST /stress-test first",
        )

    status_value = raw.get("status", "UNKNOWN")
    task_id = raw.get("task_id")

    if status_value != "COMPLETED":
        return StressTestStatusOut(
            project_id=project_id,
            status=status_value,
            task_id=task_id,
            result=None,
        )

    matrix = [AssumptionStressResult(**row) for row in raw.get("sensitivity_matrix", [])]
    shots = [AssumptionStressResult(**row) for row in raw.get("kill_shots", [])]
    partial_shots = [
        AssumptionStressResult(**row) for row in raw.get("partial_kill_shots", [])
    ]

    result = StressTestOut(
        project_id=project_id,
        status="COMPLETED",
        sensitivity_matrix=matrix,
        kill_shots=shots,
        partial_kill_shots=partial_shots,
        overall_risk_level=raw.get("overall_risk_level", "UNKNOWN"),
        baseline_conversion=raw.get("baseline_conversion", 0.0),
        assumptions_tested=raw.get("assumptions_tested", 0),
        generated_at=raw.get("generated_at", ""),
    )

    return StressTestStatusOut(
        project_id=project_id,
        status="COMPLETED",
        task_id=task_id,
        result=result,
    )


@router.delete(
    "/{project_id}/stress-test",
    summary="Clear stored stress test JSON",
    responses=_JSON_200,
    # DB write (sets stress_test_json to NULL) — cap path-spam at
    # 20/min/IP. Single-user operation, but defense-in-depth.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def clear_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    db.execute(
        text("UPDATE projects SET stress_test_json = NULL WHERE id = :id"),
        {"id": project_id},
    )
    db.commit()
    return {"message": "Stress test result cleared"}


@router.post(
    "/{project_id}/interventions",
    response_model=InterventionOut,
    summary="Generate ranked interventions (Claude)",
    # LLM-backed; cap the path at 10/min/IP so a single actor can't
    # drain LLM quota or rack up cost. The per-user monthly simulation
    # quota is enforced elsewhere (tier_enforcement); this is the
    # outer IP+path limit that protects against fast-firing requests
    # before the work even reaches the LLM.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def generate_interventions(
    project_id: int,
    payload: InterventionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short to generate interventions",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )

    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    premortem_data = getattr(project, "premortem_json", None)
    stress_test_data = getattr(project, "stress_test_json", None)

    context_used = {
        "assumptions": len(assumptions) > 0,
        "simulation": latest_sim is not None,
        "premortem": bool(premortem_data and premortem_data.get("failure_modes")),
        # A stress test contributes evidence whenever it COMPLETED with a
        # populated sensitivity_matrix — even when zero kill_shots were found
        # (a valid low-risk outcome). Keying off kill_shots alone wrongly
        # reported those runs as "no contribution"; keying off status +
        # sensitivity_matrix reflects the real persisted contract and excludes
        # RUNNING/FAILED/no-assumption payloads that carry no matrix.
        "stress_test": bool(
            stress_test_data
            and stress_test_data.get("status") == "COMPLETED"
            and stress_test_data.get("sensitivity_matrix")
        ),
    }

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    ranked_findings_text = (
        "\n".join(
            [
                f"{i + 1}. {f.get('finding', '')} → {f.get('recommended_action', '')}"
                for i, f in enumerate(findings[:5])
            ]
        )
        if findings
        else "No findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": INTERVENTION_PROMPT.format(
                        highest_value_cluster=hv_name,
                        primary_failure_domain=primary_fd,
                        cluster_narrative=narrative or "No cluster narrative available.",
                        ranked_findings_text=ranked_findings_text,
                    ),
                }
            ],
            system=(
                "You are an elite startup growth advisor. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Every intervention you suggest is specific, executable, and tied to evidence."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            fallback_key="interventions",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))
        raw_items = parsed.get("interventions", [])
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise ValueError("Claude returned empty interventions list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Intervention generation failed: {str(exc)}",
        )

    interventions: list[Intervention] = []
    for idx, item in enumerate(raw_items):
        try:
            intervention = Intervention(
                id=str(item.get("id", f"int-{idx + 1:02d}")).strip()[:50],
                title=str(item.get("title", "")).strip(),
                description=str(item.get("description", "")).strip(),
                expected_impact=str(item.get("expected_impact", "")).strip(),
                difficulty=str(item.get("difficulty", "MEDIUM")),
                estimated_cost=str(item.get("estimated_cost", "Unknown")).strip(),
                linked_assumption=item.get("linked_assumption") or None,
                linked_failure_mode=item.get("linked_failure_mode") or None,
                priority_score=float(item.get("priority_score", 0.5)),
                time_to_implement=str(item.get("time_to_implement", "Unknown")).strip(),
                success_metric=str(item.get("success_metric", "")).strip(),
            )
            interventions.append(intervention)
        except Exception:
            continue

    if not interventions:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid interventions from Claude response",
        )

    interventions.sort(key=lambda item: item.priority_score, reverse=True)
    max_n = payload.max_interventions if payload else 10
    interventions = interventions[:max_n]

    quick_wins = [
        item for item in interventions if item.difficulty == "LOW" and item.priority_score > 0.70
    ]

    now = datetime.now(timezone.utc).isoformat()
    interventions_data = {
        "interventions": [iv.model_dump() for iv in interventions],
        "quick_wins": [qw.model_dump() for qw in quick_wins],
        "generated_at": now,
        "context_used": context_used,
        "simulation_id": latest_sim.id if latest_sim else None,
    }

    project.interventions_json = interventions_data
    project.status = "INTERVENTIONS_READY"
    db.commit()

    # Bust the cached intervention-digest so the next GET
    # reflects the freshly-generated set rather than
    # waiting out the 5-min TTL. Also bust the
    # recommendations-digest (composes both intervention
    # + premortem).
    cache_invalidate(
        namespace=_INTERVENTION_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_RECOMMENDATIONS_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=now,
        context_used=context_used,
    )


@router.get(
    "/{project_id}/interventions",
    response_model=InterventionOut,
    summary="Get stored interventions JSON",
)
def get_interventions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "interventions_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No interventions generated yet — call POST /interventions first",
        )

    interventions = [Intervention(**item) for item in data.get("interventions", [])]
    quick_wins = [Intervention(**item) for item in data.get("quick_wins", [])]

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=data.get("generated_at", ""),
        context_used=data.get("context_used", {}),
    )


@router.get(
    "/{project_id}/interventions/export",
    summary="Export a project's interventions as CSV",
    response_class=StreamingResponse,
)
def export_interventions(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "intervention rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's intervention rows."""
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "interventions_json", None) or {}
    rows = []
    for list_type in ("interventions", "quick_wins"):
        for item in data.get(list_type, []) or []:
            row = dict(item)
            row["list_type"] = list_type
            rows.append(row)

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "interventions": rows,
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
                    f'attachment; filename="interventions-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = interventions_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="interventions-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/competitive-analysis",
    response_model=CompetitiveAnalysisOut,
    summary="Run competitive analysis (Claude)",
    # LLM-backed; same rationale as generate_interventions below — cap
    # path-spam so a single actor can't drain LLM quota or rack up cost.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def run_competitive_analysis(
    project_id: int,
    payload: CompetitiveAnalysisRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short for competitive analysis",
        )

    target_market = (
        payload.target_market if payload and payload.target_market else "Indian startup / SaaS / D2C market"
    )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .limit(5)
        .all()
    )
    assumptions_text = (
        "\n".join(f"- {assumption.text}" for assumption in assumptions)
        if assumptions
        else "No assumptions available."
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": COMPETITIVE_ANALYSIS_PROMPT.format(
                        description=description,
                        target_market=target_market,
                        assumptions_text=assumptions_text,
                    ),
                }
            ],
            system=(
                "You are a top-tier competitive strategy consultant with deep knowledge "
                "of Indian and global markets. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            fallback_key="competitive",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")
        parsed = json.loads(json_match.group(0))

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Competitive analysis failed: {str(exc)}",
        )

    raw_competitors = parsed.get("competitors", [])
    if not isinstance(raw_competitors, list) or len(raw_competitors) == 0:
        raise HTTPException(
            status_code=500,
            detail="Claude returned no competitors — retry the request",
        )

    competitors: list[Competitor] = []
    for item in raw_competitors:
        try:
            competitors.append(
                Competitor(
                    name=str(item.get("name", "Unknown")).strip(),
                    category=str(item.get("category", "DIRECT")),
                    features=[str(feature) for feature in item.get("features", [])[:8]],
                    pricing=str(item.get("pricing", "Unknown")).strip(),
                    positioning=str(item.get("positioning", "")).strip(),
                    target_segment=str(item.get("target_segment", "")).strip(),
                    strengths=[str(strength) for strength in item.get("strengths", [])[:5]],
                    weaknesses=[str(weakness) for weakness in item.get("weaknesses", [])[:5]],
                    india_presence=str(item.get("india_presence", "MODERATE")),
                    threat_level=str(item.get("threat_level", "MEDIUM")),
                )
            )
        except Exception:
            continue

    if not competitors:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid competitors from Claude response",
        )

    raw_gap = parsed.get("gap_analysis", {})
    gap_analysis = GapAnalysis(
        our_wins=[str(win) for win in raw_gap.get("our_wins", [])[:6]],
        our_losses=[str(loss) for loss in raw_gap.get("our_losses", [])[:6]],
        underserved_segments=[str(segment) for segment in raw_gap.get("underserved_segments", [])[:5]],
        key_differentiators=[str(item) for item in raw_gap.get("key_differentiators", [])[:5]],
        recommended_counter_moves=[str(move) for move in raw_gap.get("recommended_counter_moves", [])[:5]],
    )

    raw_map = parsed.get("market_map", {})
    first_competitor_name = competitors[0].name
    market_map = MarketMap(
        most_dangerous_competitor=str(
            raw_map.get("most_dangerous_competitor", first_competitor_name)
        ),
        easiest_to_displace=str(raw_map.get("easiest_to_displace", first_competitor_name)),
        most_similar_to_us=str(raw_map.get("most_similar_to_us", first_competitor_name)),
    )

    raw_position = str(parsed.get("overall_competitive_position", "MODERATE")).upper().strip()
    position = raw_position if raw_position in VALID_POSITIONS else "MODERATE"
    rationale = str(parsed.get("position_rationale", "")).strip()

    direct_count = sum(1 for competitor in competitors if competitor.category == "DIRECT")
    high_threat_count = sum(1 for competitor in competitors if competitor.threat_level == "HIGH")

    now = datetime.now(timezone.utc).isoformat()
    competitive_data = {
        "competitors": [competitor.model_dump() for competitor in competitors],
        "gap_analysis": gap_analysis.model_dump(),
        "market_map": market_map.model_dump(),
        "overall_competitive_position": position,
        "position_rationale": rationale,
        "generated_at": now,
        "target_market": target_market,
        "assumptions_used": len(assumptions),
    }

    project.competitive_json = competitive_data
    project.status = "COMPETITIVE_ANALYSIS_COMPLETE"
    db.commit()

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=rationale,
        direct_competitor_count=direct_count,
        high_threat_count=high_threat_count,
        generated_at=now,
    )


@router.get(
    "/{project_id}/competitive-analysis",
    response_model=CompetitiveAnalysisOut,
    summary="Get stored competitive analysis JSON",
)
def get_competitive_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "competitive_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No competitive analysis generated yet — call POST /competitive-analysis first",
        )

    competitors = [Competitor(**item) for item in data.get("competitors", [])]
    gap_analysis = GapAnalysis(**data["gap_analysis"])
    market_map = MarketMap(**data["market_map"])
    position = data.get("overall_competitive_position", "MODERATE")

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=data.get("position_rationale", ""),
        direct_competitor_count=sum(1 for competitor in competitors if competitor.category == "DIRECT"),
        high_threat_count=sum(1 for competitor in competitors if competitor.threat_level == "HIGH"),
        generated_at=data.get("generated_at", ""),
    )


@router.get(
    "/{project_id}/competitive-analysis/export",
    summary="Export a project's competitive analysis as CSV",
    response_class=StreamingResponse,
)
def export_competitive_analysis(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "competitor rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's competitor rows."""
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "competitive_json", None) or {}
    rows = list(data.get("competitors", []) or [])

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "competitors": rows,
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
                    f'attachment; filename="competitive-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = competitors_to_csv(
        rows,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="competitive-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/mvp-features/export",
    summary="Export a project's MVP feature list as CSV",
    response_class=StreamingResponse,
)
def export_mvp_features(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "feature list."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's MVP feature list."""
    project = get_owned_project(db, current_user.id, project_id)

    features = list(project.mvp_feature_list or [])

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "features": features,
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
                    f'attachment; filename="mvp-features-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = features_to_csv(
        features,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="mvp-features-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/brief/export",
    summary="Export a project's founder brief as CSV",
    response_class=StreamingResponse,
)
def export_brief(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "brief row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's founder brief."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "brief_positioning": getattr(project, "brief_positioning", None),
        "brief_features_json": getattr(project, "brief_features_json", None),
        "brief_hook": getattr(project, "brief_hook", None),
        "brief_completed_at": getattr(project, "brief_completed_at", None),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "brief": row,
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
                    f'attachment; filename="brief-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = brief_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="brief-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/tags/export",
    summary="Export a project's tags as CSV",
    response_class=StreamingResponse,
)
def export_tags(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "tag list."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's tag list."""
    project = get_owned_project(db, current_user.id, project_id)

    tags = list(project.tags or [])

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "tags": tags,
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
                    f'attachment; filename="tags-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = tags_to_csv(
        tags,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="tags-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/readings/export",
    summary="Export a project's readings as CSV",
    response_class=StreamingResponse,
)
def export_readings(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "readings row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's readings (one row per reading, plus ledger)."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "readings_json": getattr(project, "readings_json", None),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        normalized = readings_payload(row.get("readings_json"))
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "readings": normalized["readings"],
                "ledger": normalized["ledger"],
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
                    f'attachment; filename="readings-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = readings_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "2",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="readings-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/precis/export",
    summary="Export a project's precis as CSV",
    response_class=StreamingResponse,
)
def export_precis(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "precis row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's precis field."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "precis": getattr(project, "precis", None),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "precis": row,
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
                    f'attachment; filename="precis-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = precis_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="precis-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/metadata/export",
    summary="Export a project's core metadata as CSV",
    response_class=StreamingResponse,
)
def export_project_metadata(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "metadata row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's core metadata."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "title": project.title,
        "description": project.description,
        "status": project.status,
        "intake_mode": project.intake_mode,
        "is_archived": project.is_archived,
        "created_at": project.created_at,
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metadata": row,
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
                    f'attachment; filename="metadata-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = project_meta_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="metadata-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/landing/export",
    summary="Export a project's landing page fields as CSV",
    response_class=StreamingResponse,
)
def export_landing(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "landing row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's landing page fields."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "landing_page_url": getattr(project, "landing_page_url", None),
        "existing_product_description": getattr(
            project, "existing_product_description", None
        ),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "landing": row,
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
                    f'attachment; filename="landing-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = landing_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="landing-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/environment/export",
    summary="Export a project's environment row as CSV",
    response_class=StreamingResponse,
)
def export_environment(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "environment row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's environment parameters."""
    get_owned_project(db, current_user.id, project_id)

    environment = (
        db.query(Environment)
        .filter(Environment.project_id == project_id)
        .first()
    )
    row = {
        "environment_id": environment.id if environment else None,
        "project_id": project_id,
        "mode": environment.mode if environment else None,
        "consumer_volume": environment.consumer_volume if environment else None,
        "growth_rate_per_month": (
            environment.growth_rate_per_month if environment else None
        ),
        "average_order_value": (
            environment.average_order_value if environment else None
        ),
        "price_sensitivity": (
            environment.price_sensitivity if environment else None
        ),
        "market_maturity": (
            environment.market_maturity if environment else None
        ),
        "scenario_type": environment.scenario_type if environment else None,
        "manual_params_json": (
            environment.manual_params_json if environment else None
        ),
        "trend_data_json": (
            environment.trend_data_json if environment else None
        ),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "environment": row,
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
                    f'attachment; filename="environment-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = environment_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="environment-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/description/export",
    summary="Export a project's description as CSV",
    response_class=StreamingResponse,
)
def export_description(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "description row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's description field."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "description": project.description,
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "description": row,
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
                    f'attachment; filename="description-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = description_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="description-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/dossier-axis/export",
    summary="Export a project's dossier axis as CSV",
    response_class=StreamingResponse,
)
def export_dossier_axis(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "dossier-axis row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's dossier axis field."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "dossier_axis": getattr(project, "dossier_axis", None),
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dossier_axis": row,
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
                    f'attachment; filename="dossier-axis-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = dossier_axis_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dossier-axis-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/intake-mode/export",
    summary="Export a project's intake mode as CSV",
    response_class=StreamingResponse,
)
def export_intake_mode(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "intake-mode row."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's intake mode field."""
    project = get_owned_project(db, current_user.id, project_id)

    row = {
        "project_id": project.id,
        "intake_mode": project.intake_mode,
    }

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "intake_mode": row,
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
                    f'attachment; filename="intake-mode-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = intake_mode_to_csv(
        row,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "format_version": "1",
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="intake-mode-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
    status_code=200,
    summary="Create or update market environment parameters for a project",
    # DB write (creates or upserts the project's environment row).
    # Cap path-spam at 20/min/IP so a runaway script can't churn
    # through writes — environments are updated manually as the
    # founder iterates on the simulation inputs.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def create_or_update_environment(
    project_id: int,
    payload: EnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    if payload.mode.value == "SCENARIO" and payload.scenario_type:
        preset = SCENARIO_PRESETS.get(payload.scenario_type.value)
        effective = preset or ManualParams()
        if payload.manual_params:
            override = payload.manual_params.model_dump(exclude_none=True)
            merged = effective.model_dump()
            merged.update(override)
            effective = ManualParams(**merged)
    else:
        effective = payload.manual_params or ManualParams()

    existing = db.query(Environment).filter(Environment.project_id == project_id).first()

    if existing:
        existing.mode = payload.mode.value
        existing.consumer_volume = effective.consumer_volume
        existing.growth_rate_per_month = effective.growth_rate_per_month
        existing.average_order_value = effective.average_order_value
        existing.price_sensitivity = effective.price_sensitivity
        existing.market_maturity = effective.market_maturity
        existing.scenario_type = (
            payload.scenario_type.value if payload.scenario_type else None
        )
        existing.manual_params_json = effective.model_dump()
        env = existing
    else:
        env = Environment(
            project_id=project_id,
            mode=payload.mode.value,
            consumer_volume=effective.consumer_volume,
            growth_rate_per_month=effective.growth_rate_per_month,
            average_order_value=effective.average_order_value,
            price_sensitivity=effective.price_sensitivity,
            market_maturity=effective.market_maturity,
            scenario_type=(
                payload.scenario_type.value if payload.scenario_type else None
            ),
            manual_params_json=effective.model_dump(),
        )
        db.add(env)

    project.status = "ENVIRONMENT_SET"
    db.commit()
    db.refresh(env)
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
    summary="Get the environment row for a project",
)
def get_environment(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    env = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not env:
        raise HTTPException(
            status_code=404,
            detail="No environment configured. Call POST /environments first.",
        )
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments/presets",
    response_model=dict,
    summary="List scenario preset parameter bundles",
)
def get_scenario_presets(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all scenario preset configs so the frontend
    can display them to the user before they choose.
    """
    project = get_owned_project(db, current_user.id, project_id)

    return {name: preset.model_dump() for name, preset in SCENARIO_PRESETS.items()}


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Get a single project by id",
)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    _backfill_display_precis_lazy(db, project)
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post(
    "/{project_id}/re-simulate",
    summary="Queue a re-simulation and return delta vs previous run",
    responses=_JSON_200,
    # Celery-backed — cap path-spam at 30/min/IP for the same reason
    # as the simulations POST limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def re_simulate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Queues a new simulation for the project.
    Compares the two most recent completed runs (newest vs prior).
    Returns delta metrics immediately after queuing.
    """
    project = get_owned_project(db, current_user.id, project_id)

    sims = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .limit(2)
        .all()
    )

    previous_sim = sims[0] if len(sims) >= 1 else None
    older_sim = sims[1] if len(sims) >= 2 else None

    delta: dict | None = None
    if previous_sim and older_sim:
        prev_results = (
            previous_sim.results_json
            if isinstance(previous_sim.results_json, dict)
            else json.loads(previous_sim.results_json or "{}")
        )
        older_results = (
            older_sim.results_json
            if isinstance(older_sim.results_json, dict)
            else json.loads(older_sim.results_json or "{}")
        )

        prev_cr = float(
            prev_results.get("population_weighted_conversion")
            or prev_results.get("conversion_rate")
            or 0
        )
        older_cr = float(
            older_results.get("population_weighted_conversion")
            or older_results.get("conversion_rate")
            or 0
        )
        cr_delta = round(prev_cr - older_cr, 4)

        prev_clusters = prev_results.get("cluster_breakdown", {}) or {}
        older_clusters = older_results.get("cluster_breakdown", {}) or {}

        cluster_deltas: dict[str, float] = {}
        for cid in prev_clusters:
            prev_val = float(
                prev_clusters.get(cid, {}).get("conversion_rate", 0)
                if isinstance(prev_clusters.get(cid), dict)
                else prev_clusters.get(cid, 0)
            )
            older_val = float(
                older_clusters.get(cid, {}).get("conversion_rate", 0)
                if isinstance(older_clusters.get(cid), dict)
                else older_clusters.get(cid, 0)
            )
            cluster_deltas[str(cid)] = round(prev_val - older_val, 4)

        improved = sorted(cluster_deltas.items(), key=lambda x: -x[1])[:3]
        degraded = sorted(cluster_deltas.items(), key=lambda x: x[1])[:3]

        prev_assumptions = prev_results.get("assumptions_summary", []) or []
        older_assumptions = older_results.get("assumptions_summary", []) or []
        changed_count = abs(len(prev_assumptions) - len(older_assumptions))

        direction = "FLAT"
        if cr_delta > 0:
            direction = "UP"
        elif cr_delta < 0:
            direction = "DOWN"

        delta = {
            "conversion_delta": cr_delta,
            "previous_conversion": round(prev_cr, 4),
            "older_conversion": round(older_cr, 4),
            "direction": direction,
            "cluster_deltas": cluster_deltas,
            "most_improved": [
                {"cluster_id": cid, "delta": d} for cid, d in improved if d > 0
            ],
            "most_degraded": [
                {"cluster_id": cid, "delta": d} for cid, d in degraded if d < 0
            ],
            "assumptions_changed": changed_count,
            "simulation_count": len(sims),
        }

    environment = (
        db.query(Environment).filter(Environment.project_id == project_id).first()
    )
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /api/v1/projects/{id}/environments first.",
        )

    running = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status.in_(["QUEUED", "RUNNING"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation {running.id} is already {running.status} for this project.",
        )

    new_sim = Simulation(
        project_id=project_id,
        environment_id=environment.id,
        status="QUEUED",
        consumer_volume=environment.consumer_volume,
    )
    db.add(new_sim)
    db.commit()
    db.refresh(new_sim)

    task = run_full_simulation.delay(new_sim.id)
    new_sim.task_id = task.id
    db.commit()
    db.refresh(new_sim)

    return {
        "new_simulation_id": new_sim.id,
        "status": "QUEUED",
        "delta": delta,
        "message": (
            "Re-simulation queued. Delta from previous run included."
            if delta
            else "First simulation queued. No previous run to compare."
        ),
    }


@router.get(
    "/{project_id}/simulation-history",
    summary="List completed runs with key metrics for charts",
    responses=_JSON_200,
)
def get_simulation_history(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sims = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.asc())
        .all()
    )

    history: list[dict] = []
    prev_cr: float | None = None
    for sim in sims:
        results = (
            sim.results_json
            if isinstance(sim.results_json, dict)
            else json.loads(sim.results_json or "{}")
        )
        cr = float(
            results.get("population_weighted_conversion")
            or results.get("conversion_rate")
            or 0
        )
        delta_cr = round(cr - prev_cr, 4) if prev_cr is not None else None
        if delta_cr is not None and delta_cr > 0:
            direction = "UP"
        elif delta_cr is not None and delta_cr < 0:
            direction = "DOWN"
        else:
            direction = "FLAT" if delta_cr is not None else None
        history.append(
            {
                "simulation_id": sim.id,
                "status": sim.status,
                "signal_quality": sim.signal_quality,
                "conversion_rate": round(cr, 4),
                "delta_from_prev": delta_cr,
                "direction": direction,
                "created_at": sim.created_at.isoformat() if sim.created_at else None,
            }
        )
        prev_cr = cr

    return {
        "project_id": project_id,
        "total_runs": len(history),
        "history": history,
        "best_run_id": max(history, key=lambda x: x["conversion_rate"])["simulation_id"]
        if history
        else None,
    }


@router.get(
    "/{project_id}/simulation-trend",
    response_model=SimulationTrendOut,
    summary="Aggregated simulation trend analytics: status, best/worst run, volatility, slope",
    responses=_JSON_200,
)
def get_simulation_trend(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns a richer rollup than ``/simulation-history``:

      * ``status_breakdown`` — counts by status.
      * ``best_run``, ``worst_run``, ``latest_run`` — RunDetail blocks.
      * ``conversion_stats`` — count/min/max/mean/median/std of completed runs.
      * ``trend_slope`` — simple OLS slope of conversion_rate over run-index
        (None when fewer than 2 completed runs).
      * ``stability_score`` — ``1 / (1 + cv)`` where ``cv = std / mean``
        (None when fewer than 2 completed runs or mean == 0).
    """
    from datetime import datetime, timezone

    project = get_owned_project(db, current_user.id, project_id)
    sims = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.asc())
        .all()
    )
    rows = [
        {
            "id": s.id,
            "status": s.status,
            "signal_quality": s.signal_quality,
            "results_json": s.results_json,
            "created_at": s.created_at,
        }
        for s in sims
    ]
    trend = _build_simulation_trend(rows, project_id=project_id)
    trend["generated_at"] = datetime.now(timezone.utc).isoformat()
    return SimulationTrendOut(**trend)


@router.post(
    "/{project_id}/competitive-software-analysis",
    summary="Run SaaS / software competitive benchmark analysis",
    responses=_JSON_200,
    # LLM-backed benchmark — cap path-spam at 10/min/IP for the same
    # reason as the other LLM routes in this module.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def run_competitive_software_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not sim:
        raise HTTPException(
            status_code=400,
            detail="Run a simulation first before competitive analysis",
        )

    results = sim.results_json
    if isinstance(results, str):
        results = json.loads(results or "{}")
    if not isinstance(results, dict):
        results = {}

    product_type_str = str(results.get("product_type_detected", "saas")).strip().lower()
    pt_enum = _product_type_enum_from_results(product_type_str)
    pt_for_conductor = pt_enum if pt_enum in _SOFTWARE_PRODUCT_TYPES else ProductType.SAAS

    aov = float(results.get("aov") or results.get("average_order_value") or 999.0)

    assumption_rows = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.created_at.desc())
        .all()
    )
    assumptions = [
        {
            "assumption": a.text,
            "text": a.text,
            "sensitivity": a.sensitivity or "MEDIUM",
            "claim_confidence": "DESIGN_INTENT",
        }
        for a in assumption_rows
    ]

    env_params = {
        "average_order_value": aov,
        "description": project.description or "",
    }
    sq = float(sim.signal_quality or 0.0)

    conductor_result = _conductor.run(
        agents=[],
        env_params=env_params,
        assumptions=assumptions,
        product_type=pt_for_conductor,
        signal_quality=sq,
    )

    report = _comp_software_analyser.analyse(
        assumptions=assumptions,
        conductor_result=conductor_result,
        product_type=_software_benchmark_key(pt_enum),
        aov=aov,
    )

    merged = {**results, "competitive_analysis": report.to_dict()}
    sim.results_json = merged
    db.add(sim)
    db.commit()
    return report.to_dict()


@router.get(
    "/{project_id}/competitive-software-analysis",
    summary="Get stored software competitive analysis JSON",
    responses=_JSON_200,
)
def get_competitive_software_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not sim:
        return {
            "message": "No completed simulation. POST to /competitive-software-analysis first."
        }

    results = sim.results_json
    if isinstance(results, str):
        results = json.loads(results or "{}")
    if not isinstance(results, dict):
        results = {}

    comp = results.get("competitive_analysis")
    if not comp:
        return {
            "message": "No competitive analysis yet. POST to /competitive-software-analysis."
        }
    return comp


@router.post(
    "/{project_id}/regenerate-intelligence",
    response_model=ProjectOut,
    summary="Regenerate Précis and Readings for a project",
    # LLM-backed (calls generate_both → Claude) — cap path-spam at
    # 10/min/IP for the same reason as the other LLM routes in
    # this module.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def regenerate_intelligence(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    from app.services.dossier_intelligence import generate_both, readings_json_payload

    intel = generate_both(project.title, project.description)

    if intel["precis"]:
        project.precis = intel["precis"]
    bundle = readings_json_payload(
        intel["readings"],
        intel.get("ledger") or {},
    )
    if bundle:
        project.readings_json = bundle
    project.precis_title_fingerprint = _title_fingerprint(project.title)

    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get(
    "/{project_id}/next-action",
    response_model=NextBestActionOut,
    summary=(
        "The single most actionable next step the founder "
        "should take right now — composed from the latest "
        "sim's top critical finding, the oldest pending "
        "decision, and the project's calibration health"
    ),
    # Read-only composes 3 cheap queries; same cap as
    # the other lightweight project endpoints.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_next_action(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NextBestActionOut:
    """Single-answer "what should I do?" CTA.

    Priority order:
    1. Top CRITICAL architect finding from the latest
       completed simulation.
    2. Oldest pending decision in the project's queue.
    3. POORLY_CALIBRATED verdict from
       :func:`build_calibration_health`.
    4. Fallback nudge for brand-new projects.
    """
    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the three child queries.
    # Key is namespaced by user + project so tenants and
    # projects never collide.
    cached = cache_get_json(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return NextBestActionOut(
            title=cached["title"],
            action=cached["action"],
            reason=cached["reason"],
            severity=cached["severity"],
            category=cached["category"],
            source=NextBestActionSource(**cached["source"]),
            fallback=cached["fallback"],
        )

    # Latest completed simulation (newest first).
    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    latest_findings: list[dict] = []
    if latest_sim is not None and latest_sim.results_json:
        latest_findings = [
            {
                "findings": (latest_sim.results_json or {}).get(
                    "domain_findings"
                )
                or [],
            },
        ]

    # Oldest pending decision in this project.
    pending_rows = (
        db.query(Decision)
        .filter(
            Decision.project_id == project_id,
            Decision.status.in_(("PENDING", "RUNNING")),
        )
        .order_by(Decision.created_at.asc())
        .all()
    )
    pending_decisions: list[dict] = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "created_at": (
                d.created_at.isoformat()
                if d.created_at is not None else None
            ),
        }
        for d in pending_rows
    ]

    # Calibration health for the project's most recent
    # sims (last 10) — cheap sub-helper.
    calibration_health: dict | None = None
    try:
        from app.simulation.calibration_health import (
            build_calibration_health,
        )
        health_rows: list[tuple] = []
        recent_for_health = (
            db.query(
                Simulation.created_at,
                Outcome.predicted_conversion_rate,
                Outcome.actual_conversion_rate,
                Simulation.results_json,
            )
            .outerjoin(
                Outcome, Outcome.simulation_id == Simulation.id,
            )
            .filter(
                Simulation.project_id == project_id,
                Simulation.status == "COMPLETED",
            )
            .order_by(Simulation.created_at.desc())
            .limit(10)
            .all()
        )
        for r in recent_for_health:
            health_rows.append(
                (
                    r.created_at,
                    r.predicted_conversion_rate,
                    r.actual_conversion_rate,
                    (r.results_json or {}).get(
                        "domain_findings"
                    )
                    or [],
                ),
            )
        if health_rows:
            calibration_health = build_calibration_health(
                health_rows,
            )
    except Exception as _exc:
        logger.debug(
            "next-action: calibration health skipped: %s",
            _exc,
        )

    has_any_simulation = (
        db.query(Simulation.id)
        .filter(Simulation.project_id == project_id)
        .first()
        is not None
    )

    payload = build_next_best_action(
        latest_findings=latest_findings,
        pending_decisions=pending_decisions,
        calibration_health=calibration_health,
        has_any_simulation=has_any_simulation,
    )
    # Populate the cache so the next dashboard poll within
    # the 60s window short-circuits the three child queries.
    cache_set_json(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_NEXT_ACTION_CACHE_TTL_S,
    )
    return NextBestActionOut(
        title=payload["title"],
        action=payload["action"],
        reason=payload["reason"],
        severity=payload["severity"],
        category=payload["category"],
        source=NextBestActionSource(**payload["source"]),
        fallback=payload["fallback"],
    )


@router.get(
    "/{project_id}/activity-feed",
    response_model=ActivityFeedOut,
    summary=(
        "Chronological feed of the project's recent events "
        "— sims, decisions, outcomes — capped at 50 newest "
        "events with founder-readable narrative + key_signals"
    ),
    # Read-only; three cheap SELECTs capped at 50 rows.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_activity_feed(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActivityFeedOut:
    """Per-project "what just happened?" timeline.

    Composes a single payload covering the most recent
    sims, decisions, and outcomes so the dashboard can
    render a timeline tile without fanning out to
    /simulations, /decisions, and /outcomes separately.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit all three SELECTs.
    cached = cache_get_json(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ActivityFeedOut(**cached)

    sim_rows = (
        db.query(
            Simulation.id,
            Simulation.status,
            Simulation.created_at,
            Simulation.updated_at,
            Simulation.results_json,
        )
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .limit(50)
        .all()
    )
    decision_rows = (
        db.query(
            Decision.id,
            Decision.status,
            Decision.title,
            Decision.created_at,
            Decision.updated_at,
            Decision.results_json,
        )
        .filter(Decision.project_id == project_id)
        .order_by(Decision.created_at.desc())
        .limit(50)
        .all()
    )
    outcome_rows = (
        db.query(
            Outcome.id,
            Outcome.created_at,
            Outcome.actual_conversion_rate,
        )
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .limit(50)
        .all()
    )

    sim_dicts = [
        {
            "id": r.id,
            "status": r.status,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "results_json": r.results_json,
        }
        for r in sim_rows
    ]
    decision_dicts = [
        {
            "id": r.id,
            "status": r.status,
            "title": r.title,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "results_json": r.results_json,
        }
        for r in decision_rows
    ]
    outcome_dicts = [
        {
            "id": r.id,
            "created_at": r.created_at,
            "actual_conversion_rate": r.actual_conversion_rate,
        }
        for r in outcome_rows
    ]

    payload = build_activity_feed(
        sims=sim_dicts,
        decisions=decision_dicts,
        outcomes=outcome_dicts,
    )
    cache_set_json(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_ACTIVITY_FEED_CACHE_TTL_S,
    )
    return ActivityFeedOut(**payload)


@router.get(
    "/{project_id}/assumption-digest",
    response_model=AssumptionDigestOut,
    summary=(
        "Per-project digest of AI-extracted assumptions — "
        "sensitivity + category breakdown + weak-link "
        "flags + recent additions + narrative + key_signals"
    ),
    # Read-only aggregation; assumptions don't change
    # often, so a slightly higher cap is fine.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_assumption_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionDigestOut:
    """Per-project assumption digest.

    Composes a single payload covering the sensitivity /
    category distribution, weak-link flags (vague claims
    flagged HIGH/CRITICAL), recent additions, and a
    founder-readable narrative. Avoids the round-trip
    cost of /projects/{id}/assumptions + client-side
    aggregation for the dashboard's tile.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the SELECT. Key is
    # namespaced by user + project so tenants and projects
    # never collide.
    cached = cache_get_json(
        namespace=_ASSUMPTION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return AssumptionDigestOut(**cached)

    rows = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.created_at.desc())
        .all()
    )
    assumption_dicts = [
        {
            "id": a.id,
            "text": a.text,
            "category": a.category,
            "sensitivity": a.sensitivity,
            "impact_score": a.impact_score,
            "is_hidden": a.is_hidden,
            "created_at": a.created_at,
        }
        for a in rows
    ]
    payload = build_assumption_digest(assumption_dicts)

    cache_set_json(
        namespace=_ASSUMPTION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_ASSUMPTION_DIGEST_CACHE_TTL_S,
    )
    return AssumptionDigestOut(**payload)


@router.get(
    "/{project_id}/coverage-gaps",
    response_model=ProjectCoverageGapsOut,
    summary=(
        "Per-project coverage-gaps digest — which standard "
        "assumption categories has this project never "
        "explored, plus sensitivity + cluster coverage"
    ),
    # Read-only aggregation; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_project_coverage_gaps(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectCoverageGapsOut:
    """Project-scoped coverage-gaps digest.

    The user-level /me/coverage-gaps endpoint answers "which dimensions has
    this account never explored?"; this endpoint answers the same question
    for a single project. Founders can see, for example, that a project has
    never recorded a Pricing or Trust assumption, or that only 2 clusters
    were ever touched by completed simulations.
    """
    project = get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .all()
    )
    assumption_dicts = [
        {
            "category": a.category,
            "sensitivity": a.sensitivity,
            "is_hidden": a.is_hidden,
        }
        for a in rows
    ]

    cluster_ids: set[str] = set()
    sim_rows = (
        db.query(Simulation.results_json)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .all()
    )
    for (raw_results,) in sim_rows:
        if isinstance(raw_results, dict):
            results = raw_results
        elif isinstance(raw_results, str):
            try:
                results = json.loads(raw_results)
            except (ValueError, TypeError):
                # A single malformed legacy row should not take
                # the whole digest down; treat it as no results.
                results = {}
        else:
            results = {}
        if not isinstance(results, dict):
            results = {}
        breakdown = results.get("cluster_breakdown") or {}
        if not isinstance(breakdown, dict):
            continue
        for cid in breakdown.keys():
            # Cluster IDs are stable string keys in the registry
            # (e.g. ``metro_power_professional``). Preserve them as-is;
            # the helper only needs distinct values for the count.
            if cid is not None:
                cluster_ids.add(str(cid))

    payload = build_coverage_gaps(
        assumptions=assumption_dicts,
        cluster_ids=list(cluster_ids),
    )
    payload["project_id"] = project_id
    payload["project_title"] = project.title
    return ProjectCoverageGapsOut(**payload)


@router.get(
    "/{project_id}/coverage-gaps/export",
    response_class=StreamingResponse,
    summary=(
        "Export the coverage-gaps digest as CSV (or JSON with "
        "?format=json)"
    ),
    # Same DB reads as the JSON coverage-gaps endpoint; cap polling so a
    # dashboard loop can't drive repeated coverage aggregation.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_project_coverage_gaps(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "coverage-gaps payload. Unsupported values return a 400 "
            "response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's coverage-gaps digest.

    Computes the same payload as ``GET /projects/{id}/coverage-gaps``,
    then renders it as CSV (default) or JSON. The CSV includes the
    summary, one row per covered / missing category, the sensitivity
    breakdown, and the key signals so a founder can see at a glance
    which assumption dimensions their project has never explored.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )

    payload = get_project_coverage_gaps(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )

    metadata = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "project_id": project_id,
    }

    if fmt == "json":
        body = coverage_gaps_to_json(payload, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="coverage-gaps-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = coverage_gaps_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="coverage-gaps-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/convergence",
    response_model=ConvergenceCheckOut,
    summary=(
        "Per-project convergence check — do repeated sims "
        "of the same brief agree (CONVERGED), vary mildly "
        "(MILDLY_VARIANT), or scatter (DIVERGED)?"
    ),
    # Read-only aggregation; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_convergence_check(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConvergenceCheckOut:
    """Per-project convergence check.

    Computes the coefficient of variation (CV) across the
    most recent ``predicted_conversion_rate`` values and
    buckets the result into a verdict:
    CV < 5% → CONVERGED, 5-15% → MILDLY_VARIANT,
    >= 15% → DIVERGED. Fewer than 3 usable sims →
    INSUFFICIENT_DATA.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the SELECT.
    cached = cache_get_json(
        namespace=_CONVERGENCE_CHECK_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ConvergenceCheckOut(**cached)

    from app.simulation.convergence_check import (
        MAX_SIMS_CONSIDERED,
    )

    rows = (
        db.query(
            Simulation.id,
            Simulation.created_at,
            Simulation.status,
            Simulation.results_json,
        )
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .limit(MAX_SIMS_CONSIDERED)
        .all()
    )
    sim_dicts = [
        {
            "id": r.id,
            "created_at": r.created_at,
            "status": r.status,
            "predicted_conversion_rate": (
                (r.results_json or {}).get("predicted_conversion_rate")
                if isinstance(r.results_json, dict)
                else None
            ),
            "results_json": r.results_json,
        }
        for r in rows
    ]
    payload = build_convergence_check(sim_dicts)
    cache_set_json(
        namespace=_CONVERGENCE_CHECK_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_CONVERGENCE_CHECK_CACHE_TTL_S,
    )
    return ConvergenceCheckOut(**payload)


@router.get(
    "/{project_id}/intervention-digest",
    response_model=InterventionDigestOut,
    summary=(
        "Per-project digest of AI-generated interventions — "
        "difficulty/priority/category breakdown + quick "
        "wins + top recommendations + narrative + stale "
        "flag + key_signals"
    ),
    # Read-only composition of the project's interventions_json.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_intervention_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterventionDigestOut:
    """Per-project intervention digest.

    Composes a single payload covering the difficulty /
    priority / category breakdown, the quick-win count,
    the top recommendations, the staleness flag, and a
    founder-readable narrative + key_signals so the
    dashboard can render a "what should I change next?"
    tile without fanning out to the intervention generator.
    """
    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit.
    cached = cache_get_json(
        namespace=_INTERVENTION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return InterventionDigestOut(**cached)

    payload = build_intervention_digest(
        interventions_data=getattr(
            project, "interventions_json", None,
        ),
    )
    cache_set_json(
        namespace=_INTERVENTION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_INTERVENTION_DIGEST_CACHE_TTL_S,
    )
    return InterventionDigestOut(**payload)


@router.get(
    "/{project_id}/health",
    response_model=ProjectHealthOut,
    summary=(
        "Per-project qualitative health score — 0-100 + "
        "HEALTHY/NEEDS_ATTENTION/AT_RISK verdict composed "
        "from sim confidence + critical findings + "
        "pending decisions + outcome + assumption weak links"
    ),
    # Read-only composition; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_project_health(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectHealthOut:
    """Per-project qualitative health score.

    Composes a 0-100 health score from five dimensions +
    penalties. Different from /me/account-health (which is
    user-level across all projects) — this answers "is THIS
    specific project in good shape?".

    Use case: the project-list view sorts projects by this
    score, surfacing the worst first.
    """
    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit.
    cached = cache_get_json(
        namespace=_PROJECT_HEALTH_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectHealthOut(**cached)

    # Latest completed sim.
    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    sim_confidence: float | None = None
    critical_finding_count = 0
    if latest_sim is not None:
        sim_confidence = getattr(latest_sim, "confidence_score", None)
        if sim_confidence is None and latest_sim.results_json:
            agg = latest_sim.results_json.get("aggregated") or {}
            sim_confidence = agg.get("confidence_score")
        if sim_confidence is not None:
            sim_confidence = float(sim_confidence) / 100.0
        # Count CRITICAL findings.
        for f in (latest_sim.results_json or {}).get(
            "domain_findings", []
        ) or []:
            if isinstance(f, dict) and (
                f.get("severity") == "CRITICAL"
                or f.get("level") == "CRITICAL"
            ):
                critical_finding_count += 1

    # Pending decisions.
    pending_decision_count = (
        db.query(Decision)
        .filter(
            Decision.project_id == project_id,
            Decision.status.in_(("PENDING", "RUNNING")),
        )
        .count()
    )

    # Any recorded outcome?
    has_outcome = (
        db.query(Outcome.id)
        .filter(Outcome.project_id == project_id)
        .first()
        is not None
    )

    # Assumption weak-link count.
    weak_link_count = 0
    from app.simulation.assumption_digest import (
        build_assumption_digest,
    )
    assumption_rows = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
            Assumption.sensitivity.in_(("HIGH", "CRITICAL")),
        )
        .all()
    )
    if assumption_rows:
        digest = build_assumption_digest([
            {
                "id": a.id,
                "sensitivity": a.sensitivity,
                "specificity_score": a.specificity_score,
                "impact_score": a.impact_score,
                "is_hidden": a.is_hidden,
            }
            for a in assumption_rows
        ])
        weak_link_count = digest["weak_link_count"]

    payload = build_project_health(
        sim_confidence=sim_confidence,
        critical_finding_count=critical_finding_count,
        pending_decision_count=pending_decision_count,
        weak_link_count=weak_link_count,
        has_outcome=has_outcome,
    )
    cache_set_json(
        namespace=_PROJECT_HEALTH_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_PROJECT_HEALTH_CACHE_TTL_S,
    )
    return ProjectHealthOut(**payload)


@router.get(
    "/{project_id}/health/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's health scorecard as CSV (or JSON "
        "with ?format=json)"
    ),
    # Same read cost as the JSON health endpoint; cap polling so a
    # dashboard loop can't drive repeated child-row scans.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_project_health(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly scorecard; ``json`` returns the "
            "raw project-health payload. Unsupported values return "
            "a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's health scorecard.

    Reuses the same cached payload as ``GET /projects/{id}/health``.
    ``format=csv`` renders the score summary, per-component breakdown,
    and key signals as a multi-section spreadsheet. ``format=json``
    returns the raw payload for machine consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected "
                "'csv' or 'json'"
            ),
        )

    payload = get_project_health(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "project_id": project_id,
    }

    if fmt == "json":
        json_text = project_health_to_json(payload, metadata=metadata)
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="health-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = project_health_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="health-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/premortem-digest",
    response_model=PremortemDigestOut,
    summary=(
        "Per-project premortem digest - composes "
        "project.premortem_json into a one-shot 'what "
        "could go wrong?' payload"
    ),
    # Read-only composition of project.premortem_json.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_premortem_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PremortemDigestOut:
    """Per-project premortem digest.

    Composes a single payload covering the severity
    breakdown, top failure modes (impact DESC), and a
    founder-readable narrative + key_signals. Avoids
    fanning out to /premortem + client-side aggregation
    for the dashboard's 'what could go wrong?' tile.
    """
    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit.
    cached = cache_get_json(
        namespace=_PREMORTEM_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return PremortemDigestOut(**cached)

    payload = build_premortem_digest(
        premortem_data=getattr(project, "premortem_json", None),
    )
    cache_set_json(
        namespace=_PREMORTEM_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_PREMORTEM_DIGEST_CACHE_TTL_S,
    )
    return PremortemDigestOut(**payload)


@router.get(
    "/{project_id}/recommendations-digest",
    response_model=RecommendationsDigestOut,
    summary=(
        "Per-project recommendations digest - composed "
        "from premortem top failure modes + intervention "
        "top recommendations into a single ranked payload"
    ),
    # Read-only composition; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_recommendations_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationsDigestOut:
    """Per-project recommendations digest.

    Composes the premortem top failure modes and the
    intervention top recommendations into one ranked,
    capped payload so the dashboard's recommendations
    tile can render one paragraph + key signals.
    """
    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit - short-circuit both source digests.
    cached = cache_get_json(
        namespace=_RECOMMENDATIONS_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return RecommendationsDigestOut(**cached)

    premortem_payload = build_premortem_digest(
        premortem_data=getattr(project, "premortem_json", None),
    )
    intervention_payload = build_intervention_digest(
        interventions_data=getattr(
            project, "interventions_json", None,
        ),
    )
    payload = build_recommendations_digest(
        premortem_digest=premortem_payload,
        intervention_digest=intervention_payload,
    )
    cache_set_json(
        namespace=_RECOMMENDATIONS_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_RECOMMENDATIONS_DIGEST_CACHE_TTL_S,
    )
    return RecommendationsDigestOut(**payload)


@router.get(
    "/{project_id}/recommendations/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's ranked recommendations as CSV (or JSON "
        "with ?format=json)"
    ),
    # Same composition cost as the JSON digest endpoint; cap polling so a
    # dashboard loop can't drive repeated premortem/intervention reads.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_project_recommendations(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly ranked table; ``json`` returns the "
            "raw recommendations payload. Unsupported values return "
            "a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's recommendations digest.

    Reuses the same composition path as ``GET /projects/{id}/recommendations-digest``.
    ``format=csv`` renders the summary, one row per ranked recommendation,
    and the key signals. ``format=json`` returns the raw payload for
    machine consumers.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected "
                "'csv' or 'json'"
            ),
        )

    payload = get_recommendations_digest(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": current_user.id,
        "format_version": "1",
        "project_id": project_id,
    }

    if fmt == "json":
        json_text = recommendations_to_json(payload, metadata=metadata)
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="recommendations-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = recommendations_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="recommendations-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/adoption-milestones",
    response_model=AdoptionMilestonesOut,
    summary=(
        "Per-project adoption milestones - onboarding "
        "progress tracker (brief / assumptions / first sim / "
        "first decision / first outcome / premortem / "
        "interventions)"
    ),
    # Read-only composition of project + child-row counts.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_adoption_milestones(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdoptionMilestonesOut:
    """Per-project adoption milestones digest.

    Composes a single onboarding progress payload ("have
    you done the basics?") so the dashboard can render a
    milestone progress bar without each component being
    checked separately.
    """
    # Cache hit - short-circuit the 5 child-row counts.
    cached = cache_get_json(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return AdoptionMilestonesOut(**cached)

    project = get_owned_project(db, current_user.id, project_id)

    # Count assumptions (non-hidden).
    assumption_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .count()
    )
    simulation_count = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .count()
    )
    decision_count = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .count()
    )
    outcome_count = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .count()
    )

    payload = build_adoption_milestones(
        brief_completed=project.brief_completed_at is not None,
        assumption_count=assumption_count,
        simulation_count=simulation_count,
        decision_count=decision_count,
        outcome_count=outcome_count,
        premortem_present=getattr(
            project, "premortem_json", None,
        ) is not None,
        interventions_present=getattr(
            project, "interventions_json", None,
        ) is not None,
    )
    cache_set_json(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_ADOPTION_MILESTONES_CACHE_TTL_S,
    )
    return AdoptionMilestonesOut(**payload)


@router.get(
    "/{project_id}/export",
    response_model=ProjectExportOut,
    summary=(
        "Full project export - brief + assumptions + sims + "
        "decisions + outcomes + premortem + interventions "
        "in a single JSON bundle for handoff/archive"
    ),
    # Read-only composition; bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_project_export(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectExportOut:
    """Full project export bundle.

    Composes a JSON-ready payload covering every row
    tied to the project: brief fields, assumptions, every
    simulation row, every decision row, every outcome
    row, plus the AI-generated premortem and
    intervention analyses. Useful for offline archive,
    co-founder handoff, or as LLM context.
    """
    # Cache hit — short-circuit the 4 child SELECTs.
    cached = cache_get_json(
        namespace=_PROJECT_EXPORT_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectExportOut(**cached)

    project = get_owned_project(db, current_user.id, project_id)

    project_dict = {
        "id": getattr(project, "id", None),
        "title": getattr(project, "title", None),
        "description": getattr(project, "description", None),
        "status": getattr(project, "status", None),
        "intake_mode": getattr(project, "intake_mode", None),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
    brief_dict = {
        "positioning": getattr(project, "brief_positioning", None),
        "features": getattr(project, "brief_features_json", None),
        "hook": getattr(project, "brief_hook", None),
        "completed_at": getattr(
            project, "brief_completed_at", None,
        ),
    }
    if isinstance(brief_dict.get("features"), str):
        import json as _json
        try:
            brief_dict["features"] = _json.loads(
                brief_dict["features"],
            )
        except Exception:
            brief_dict["features"] = []

    # Pull child rows.
    assumption_rows = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .all()
    )
    assumption_dicts = [
        {
            "id": a.id,
            "text": a.text,
            "category": a.category,
            "sensitivity": a.sensitivity,
            "impact_score": a.impact_score,
            "is_hidden": a.is_hidden,
            "created_at": a.created_at,
        }
        for a in assumption_rows
    ]
    simulation_rows = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.asc())
        .all()
    )
    simulation_dicts = [
        {
            "id": s.id,
            "status": s.status,
            "predicted_conversion_rate": (
                s.predicted_conversion_rate
            ),
            "actual_conversion_rate": (
                s.actual_conversion_rate
            ),
            "results_json": s.results_json,
            "confidence_score": s.confidence_score,
            "created_at": s.created_at,
        }
        for s in simulation_rows
    ]
    decision_rows = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .order_by(Decision.created_at.asc())
        .all()
    )
    decision_dicts = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "created_at": d.created_at,
        }
        for d in decision_rows
    ]
    outcome_rows = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.asc())
        .all()
    )
    outcome_dicts = [
        {
            "id": o.id,
            "actual_conversion_rate": o.actual_conversion_rate,
            "actual_mrr": o.actual_mrr,
            "calibration_score": o.calibration_score,
            "created_at": o.created_at,
        }
        for o in outcome_rows
    ]

    payload = build_project_export(
        project_row=project_dict,
        brief_dict=brief_dict,
        assumption_dicts=assumption_dicts,
        simulation_dicts=simulation_dicts,
        decision_dicts=decision_dicts,
        outcome_dicts=outcome_dicts,
        premortem_data=getattr(
            project, "premortem_json", None,
        ),
        interventions_data=getattr(
            project, "interventions_json", None,
        ),
    )
    cache_set_json(
        namespace=_PROJECT_EXPORT_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_PROJECT_EXPORT_CACHE_TTL_S,
    )
    return ProjectExportOut(**payload)


@router.get(
    "/{project_id}/stale-check",
    response_model=StaleCheckOut,
    summary=(
        "Per-project data-freshness check - which sources "
        "feeding the project are out of date (assumptions / "
        "sims / outcomes / decisions / premortem / "
        "interventions)"
    ),
    # Read-only composition of MAX-of-child-row timestamps.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_stale_check(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaleCheckOut:
    """Per-project stale-check digest.

    For each of 6 data sources (assumptions, sims,
    outcomes, decisions, premortem, interventions), the
    digest reports how many days since the source was
    last refreshed + a staleness severity + a concrete
    recommendation.

    Useful as the dashboard's "are my predictions still
    trustworthy?" tile - founders often don't realise
    their assumptions are weeks old.
    """
    # Cache hit - short-circuit the 4 child-row
    # MAX-of-timestamp queries + 2 JSONB-timestamp parses.
    cached = cache_get_json(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return StaleCheckOut(**cached)

    project = get_owned_project(db, current_user.id, project_id)

    # Latest assumption extraction.
    latest_assumption = (
        db.query(Assumption.created_at)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.created_at.desc())
        .first()
    )
    # Latest COMPLETED sim.
    latest_completed_sim = (
        db.query(Simulation.created_at)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    # Latest outcome.
    latest_outcome = (
        db.query(Outcome.created_at)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .first()
    )
    # Latest COMPLETED decision.
    latest_completed_decision = (
        db.query(Decision.created_at)
        .filter(
            Decision.project_id == project_id,
            Decision.status == "COMPLETED",
        )
        .order_by(Decision.created_at.desc())
        .first()
    )
    # Latest premortem and intervention timestamps come
    # from JSONB payloads (generation time, not create_at).
    premortem_payload = getattr(project, "premortem_json", None)
    interventions_payload = getattr(
        project, "interventions_json", None,
    )

    def _parse_iso_dt(raw: object) -> object | None:
        if not isinstance(raw, dict):
            return None
        ts = raw.get("generated_at")
        if not isinstance(ts, str):
            return None
        from datetime import datetime as _dt
        try:
            return _dt.fromisoformat(ts)
        except Exception:
            return None

    latest_premortem_at = _parse_iso_dt(premortem_payload)
    latest_intervention_at = _parse_iso_dt(interventions_payload)

    payload = build_stale_check(
        latest_assumption_at=(
            latest_assumption[0] if latest_assumption else None
        ),
        latest_sim_completed_at=(
            latest_completed_sim[0]
            if latest_completed_sim else None
        ),
        latest_outcome_at=(
            latest_outcome[0] if latest_outcome else None
        ),
        latest_decision_completed_at=(
            latest_completed_decision[0]
            if latest_completed_decision else None
        ),
        latest_premortem_at=latest_premortem_at,
        latest_intervention_at=latest_intervention_at,
    )
    cache_set_json(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_STALE_CHECK_CACHE_TTL_S,
    )
    return StaleCheckOut(**payload)


@router.get(
    "/{project_id}/latest-snapshot",
    response_model=LatestSnapshotOut,
    summary=(
        "Per-project latest snapshot - focused view of "
        "the most recent sim / decision / outcome / "
        "assumption extraction"
    ),
    # Read-only; 4 cheap max-by-id queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_latest_snapshot(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LatestSnapshotOut:
    """Per-project latest snapshot.

    Composes the "what is the current state of this
    project?" payload by pulling just the most-recent
    row from each of the 4 feed tables (simulations,
    decisions, outcomes, assumptions). Faster than
    project-export (no historical bundle) and tighter
    than projects-summary (per-user grid).
    """
    # Cache hit - short-circuit the 4 max-by-id queries.
    cached = cache_get_json(
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return LatestSnapshotOut(**cached)

    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.id.desc())
        .first()
    )
    latest_dec = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .order_by(Decision.id.desc())
        .first()
    )
    latest_out = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.id.desc())
        .first()
    )
    latest_ass = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.desc())
        .first()
    )

    def _row_dict(row: object | None) -> dict | None:
        if row is None:
            return None
        return {
            c.key: getattr(row, c.key, None)
            for c in row.__table__.columns
        }

    payload = build_latest_snapshot(
        project_id=project.id,
        project_title=getattr(project, "title", None),
        project_status=getattr(project, "status", None),
        brief_completed=getattr(
            project, "brief_completed_at", None,
        ) is not None,
        latest_simulation_row=_row_dict(latest_sim),
        latest_decision_row=_row_dict(latest_dec),
        latest_outcome_row=_row_dict(latest_out),
        latest_assumption_row=_row_dict(latest_ass),
    )
    cache_set_json(
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_LATEST_SNAPSHOT_CACHE_TTL_S,
    )
    return LatestSnapshotOut(**payload)


@router.get(
    "/{project_id}/status-banner",
    response_model=StatusBannerOut,
    summary=(
        "Per-project one-liner status banner - "
        "'Healthy' / 'Action needed' / 'Stale' / 'Empty' "
        "based on the project's recent activity"
    ),
    # Read-only; 3 cheap queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_status_banner(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StatusBannerOut:
    """Status banner.

    Composes a single one-liner status string for the
    project's header. Cheap to fetch, useful for the
    project's at-a-glance state.
    """

    project = get_owned_project(db, current_user.id, project_id)

    # Cache hit - short-circuit the 3 cheap queries.
    cached = cache_get_json(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return StatusBannerOut(**cached)

    # Latest completed sim.
    latest_completed_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    has_completed_sim = latest_completed_sim is not None
    days_since_latest_sim: int | None = None
    if has_completed_sim and latest_completed_sim.created_at is not None:
        ts = latest_completed_sim.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        days_since_latest_sim = max(0, delta.days)

    # Pending decisions count.
    pending_decision_count = (
        db.query(Decision)
        .filter(
            Decision.project_id == project_id,
            Decision.status.in_(("PENDING", "RUNNING")),
        )
        .count()
    )

    # Assumption count + latest assumption extraction age.
    assumption_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .count()
    )
    days_since_latest_assumption_extraction: int | None = None
    if assumption_count > 0:
        latest_assumption = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == project_id,
                Assumption.is_hidden.is_(False),
            )
            .order_by(Assumption.created_at.desc())
            .first()
        )
        if (
            latest_assumption is not None
            and latest_assumption.created_at is not None
        ):
            ts = latest_assumption.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts
            days_since_latest_assumption_extraction = max(
                0, delta.days,
            )

    payload = build_status_banner(
        brief_completed=getattr(
            project, "brief_completed_at", None,
        ) is not None,
        assumption_count=assumption_count,
        has_completed_sim=has_completed_sim,
        days_since_latest_sim=days_since_latest_sim,
        pending_decision_count=pending_decision_count,
        days_since_latest_assumption_extraction=(
            days_since_latest_assumption_extraction
        ),
    )
    cache_set_json(
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_STATUS_BANNER_CACHE_TTL_S,
    )
    return StatusBannerOut(**payload)


@router.get(
    "/{project_id}/confidence-explainer",
    response_model=ConfidenceExplainerOut,
    summary=(
        "Per-project confidence explainer - decomposes the "
        "latest completed sim's confidence score into 5 "
        "contributing factors (sample volume, conversion "
        "agreement, assumption coverage, assumption "
        "freshness, outcome history depth)"
    ),
    # Read-only; 4 cheap queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_confidence_explainer(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConfidenceExplainerOut:
    """Confidence explainer.

    Decomposes the latest completed sim's confidence
    score into 5 factors so the dashboard can show
    'why is my confidence 0.85?' instead of just '0.85'.
    """
    # Cache hit - short-circuit the 4 cheap queries.
    # Checked BEFORE the DB query below so cache hits
    # skip all DB work (including the no-sim early-return).
    cached = cache_get_json(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ConfidenceExplainerOut(**cached)

    project = get_owned_project(db, current_user.id, project_id)

    # Latest completed sim.
    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if latest_sim is None:
        return ConfidenceExplainerOut(
            narrative=(
                "No completed simulation yet. Run one to see "
                "the confidence breakdown."
            ),
        )

    confidence_score = getattr(
        latest_sim, "confidence_score", None,
    )
    if confidence_score is None:
        agg = (latest_sim.results_json or {}).get(
            "aggregated", {},
        )
        confidence_score = agg.get("confidence_score")
    if confidence_score is not None:
        confidence_score = float(confidence_score) / 100.0

    # Sample volume = sim's consumer_volume (the number
    # of simulated agents).
    sample_volume = _safe_int(getattr(
        latest_sim, "consumer_volume", 0,
    ))

    # Conversion agreement = predicted_conversion_rate
    # (the higher the rate, the more agents agreed).
    agreement_rate = _safe_float(getattr(
        latest_sim, "predicted_conversion_rate", None,
    ))

    # Assumption coverage = count of assumptions / 5
    # (5 sensitivity bands: LOW/MEDIUM/HIGH/CRITICAL
    # + 1 implicit; capped at 1.0).
    assumption_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.is_hidden.is_(False),
        )
        .count()
    )
    assumption_coverage = min(1.0, assumption_count / 5.0)

    # Assumption freshness = days since latest assumption.
    days_since_latest_assumption: int | None = None
    if assumption_count > 0:
        latest_assumption = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == project_id,
                Assumption.is_hidden.is_(False),
            )
            .order_by(Assumption.created_at.desc())
            .first()
        )
        if (
            latest_assumption is not None
            and latest_assumption.created_at is not None
        ):
            ts = latest_assumption.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts
            days_since_latest_assumption = max(0, delta.days)

    # Outcome history depth = count of past outcomes for
    # the project (calibration target).
    outcome_history_depth = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .count()
    )

    payload = build_confidence_explainer(
        confidence_score=confidence_score,
        sample_volume=sample_volume,
        agreement_rate=agreement_rate,
        assumption_coverage=assumption_coverage,
        days_since_latest_assumption=(
            days_since_latest_assumption
        ),
        outcome_history_depth=outcome_history_depth,
    )
    cache_set_json(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_CONFIDENCE_EXPLAINER_CACHE_TTL_S,
    )
    return ConfidenceExplainerOut(**payload)


def _safe_int(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return 0


def _safe_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


_COHORT_DRIFT_CACHE_NAMESPACE = "project_cohort_drift"
_COHORT_DRIFT_CACHE_TTL_S = 60


@router.get(
    "/{project_id}/cohort-drift",
    response_model=ClusterCohortDriftOut,
    summary="Consumer cohort conversion drift across simulation runs",
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_cluster_cohort_drift(
    project_id: int,
    baseline_sim_id: int | None = Query(
        None, description="Optional baseline simulation ID"
    ),
    latest_sim_id: int | None = Query(
        None, description="Optional comparison simulation ID"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClusterCohortDriftOut:
    """Analyze consumer cluster conversion drift for a project.

    Compares conversion rates across consumer archetypes between two
    simulation runs (defaults to oldest vs newest completed simulation).
    """
    project = get_owned_project(db, current_user.id, project_id)

    cache_params = {
        "project_id": project_id,
        "baseline_sim_id": baseline_sim_id,
        "latest_sim_id": latest_sim_id,
    }
    cached = cache_get_json(
        namespace=_COHORT_DRIFT_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
    )
    if cached is not None:
        return ClusterCohortDriftOut(**cached)

    completed_sims = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.id.asc())
        .all()
    )

    baseline_json = {}
    latest_json = {}

    if completed_sims:
        sim_map = {s.id: s for s in completed_sims}

        base_sim = (
            sim_map.get(baseline_sim_id)
            if baseline_sim_id
            else completed_sims[0]
        )
        latest_sim = (
            sim_map.get(latest_sim_id)
            if latest_sim_id
            else completed_sims[-1]
        )

        if base_sim:
            baseline_json = base_sim.results_json or {}
        if latest_sim:
            latest_json = latest_sim.results_json or {}

    payload = compute_cluster_cohort_drift(
        baseline_results=baseline_json,
        latest_results=latest_json,
    )

    cache_set_json(
        namespace=_COHORT_DRIFT_CACHE_NAMESPACE,
        params=cache_params,
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_COHORT_DRIFT_CACHE_TTL_S,
    )
    return ClusterCohortDriftOut(**payload)


@router.get(
    "/{project_id}/simulations/export",
    summary="Export a project's simulations as CSV",
    response_class=StreamingResponse,
)
def export_project_simulations(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "simulation rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's simulation rows."""
    get_owned_project(db, current_user.id, project_id)

    simulations = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .all()
    )
    rows = [
        {
            "simulation_id": simulation.id,
            "project_id": simulation.project_id,
            "status": simulation.status,
            "created_at": simulation.created_at,
            "signal_quality": simulation.signal_quality,
            "product_type": (
                (simulation.results_json or {}).get("product_type_detected", "")
                if simulation.results_json
                else ""
            ),
            "population_weighted_conversion": (
                (simulation.results_json or {}).get(
                    "population_weighted_conversion"
                )
                if simulation.results_json
                else None
            ),
        }
        for simulation in simulations
    ]

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "simulations": rows,
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
                    f'attachment; filename="simulations-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = simulations_to_csv(rows)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="simulations-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )
