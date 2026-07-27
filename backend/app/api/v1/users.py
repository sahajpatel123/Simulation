from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import (
    cache_get_json,
    cache_set_json,
)
from app.core.tier_enforcement import TIER_LIMITS
from app.models.assumption import Assumption
from app.models.decision import Decision
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.user import (
    AccountHealthOut,
    CoverageGapsOut,
    DecisionRateOut,
    DecisionToOutcomeDelayOut,
    DecisionVelocityOut,
    DigestSnapshotOut,
    InsightsOut,
    LastTouchedProjectOut,
    LastWeekStatsOut,
    MostActiveProjectOut,
    NotificationsOut,
    OutcomeRateOut,
    OutcomeVelocityOut,
    PortfolioHealthSnapshotOut,
    ProjectsByStatusOut,
    ProjectsNeedingAttentionOut,
    ProjectsSummaryOut,
    QuickStatsOut,
    RunsThisMonthOut,
    TagTaxonomyOut,
    UsageByWeekOut,
    UserDashboardOut,
    WeeklyDigestOut,
)
from app.simulation.account_health import build_account_health
from app.simulation.calibration_health import (
    build_calibration_health,
)
from app.simulation.coverage_gaps import build_coverage_gaps
from app.simulation.decision_rate import build_decision_rate
from app.simulation.sim_failure_rate import (
    build_sim_failure_rate,
)
from app.simulation.decision_to_outcome_delay import (
    build_decision_to_outcome_delay,
)
from app.simulation.decision_velocity import (
    build_decision_velocity,
)
from app.simulation.digest_snapshot import build_digest_snapshot
from app.simulation.insights import build_insights
from app.simulation.intervention_digest import build_intervention_digest
from app.simulation.last_touched_project import (
    build_last_touched_project,
)
from app.simulation.last_week_stats import (
    build_last_week_stats,
)
from app.simulation.most_active_project import (
    build_most_active_project,
)
from app.simulation.notifications import build_notifications
from app.simulation.outcome_rate import build_outcome_rate
from app.simulation.outcome_velocity import (
    build_outcome_velocity,
)
from app.simulation.portfolio_health_snapshot import (
    build_portfolio_health_snapshot,
)
from app.simulation.premortem_digest import build_premortem_digest
from app.simulation.projects_by_status import (
    build_projects_by_status,
)
from app.simulation.projects_needing_attention import (
    build_projects_needing_attention,
)
from app.simulation.projects_summary import build_projects_summary
from app.simulation.quick_stats import build_quick_stats
from app.simulation.runs_this_month import (
    build_runs_this_month,
)
from app.simulation.tag_taxonomy import build_tag_taxonomy
from app.simulation.usage_by_week import build_usage_by_week
from app.simulation.user_dashboard import (
    build_user_dashboard,
)
from app.simulation.weekly_digest import build_weekly_digest

router = APIRouter(prefix="/users", tags=["users"])

# Read-mostly account snapshot. A short TTL absorbs the
# Account-page polling without making tier-quota reads
# look stale.
_USER_DASHBOARD_CACHE_TTL_S: int = 30
_USER_DASHBOARD_CACHE_NAMESPACE: str = "user-dashboard"

# Qualitative health verdict (0-100 score). Slightly
# longer TTL since it composes heavier queries.
_USER_ACCOUNT_HEALTH_CACHE_TTL_S: int = 60
_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE: str = "user-account-health"

# Coverage gaps - recomputed on extract-assumptions +
# new completed sims only, so a longer 5-min TTL is fine.
_USER_COVERAGE_GAPS_CACHE_TTL_S: int = 300
_USER_COVERAGE_GAPS_CACHE_NAMESPACE: str = "user-coverage-gaps"

# Notifications inbox - short TTL because the bell icon
# refreshes often and blindspot detection can mutate
# the underlying rows.
_USER_NOTIFICATIONS_CACHE_TTL_S: int = 60
_USER_NOTIFICATIONS_CACHE_NAMESPACE: str = "user-notifications"

# Weekly digest - rolling 7d activity recap. Short TTL:
# the home-screen weekly tile refreshes often.
_USER_WEEKLY_DIGEST_CACHE_TTL_S: int = 60
_USER_WEEKLY_DIGEST_CACHE_NAMESPACE: str = "user-weekly-digest"

# Projects summary - lightweight per-project grid cards.
# 60s TTL: the dashboard list view renders often, but
# each card's counts only mutate when sims/decisions/
# outcomes are added.
_USER_PROJECTS_SUMMARY_CACHE_TTL_S: int = 60
_USER_PROJECTS_SUMMARY_CACHE_NAMESPACE: str = (
    "user-projects-summary"
)

# Usage by week - 12-week rolling history. 60s TTL: the
# chart refreshes often but each week's counts only
# update when a new sim/decision/outcome lands.
_USER_USAGE_BY_WEEK_CACHE_TTL_S: int = 60
_USER_USAGE_BY_WEEK_CACHE_NAMESPACE: str = (
    "user-usage-by-week"
)

# Projects by status - status pie-chart data. 60s TTL:
# status only changes on a few project-mutating routes
# (create / premortem / interventions / clear-archive).
_USER_PROJECTS_BY_STATUS_CACHE_TTL_S: int = 60
_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE: str = (
    "user-projects-by-status"
)

# Tag taxonomy - tag + project_count map. 5-min TTL:
# tags change rarely (only on project create / patch
# / archive), so a longer staleness window is fine.
_USER_TAG_TAXONOMY_CACHE_TTL_S: int = 300
_USER_TAG_TAXONOMY_CACHE_NAMESPACE: str = "user-tag-taxonomy"

# Most-active project - "where should I focus?" tile.
# 60s TTL: 3 GROUP BY queries in the route, so the
# cache matters more than for the lighter endpoints.
_USER_MOST_ACTIVE_PROJECT_CACHE_TTL_S: int = 60
_USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE: str = (
    "user-most-active-project"
)

# Quick stats - minimal one-liner for mobile widgets.
# 60s TTL: 4 cheap COUNTs in the route, but the dashboard
# sidebar refreshes often, so cache + bust.
_USER_QUICK_STATS_CACHE_TTL_S: int = 60
_USER_QUICK_STATS_CACHE_NAMESPACE: str = "user-quick-stats"

# Portfolio health snapshot - 0-100 user-level rollup.
# 60s TTL: 5-min-style cache works for the dashboard
# header that refreshes often.
_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_TTL_S: int = 60
_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE: str = (
    "user-portfolio-health-snapshot"
)

# Last-touched project - "where was I last?" tile.
# 60s TTL: 3 MAX-by-id queries in the route.
_USER_LAST_TOUCHED_PROJECT_CACHE_TTL_S: int = 60
_USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE: str = (
    "user-last-touched-project"
)

# Runs-this-month - tier-quota widget integer.
# 30s TTL: the widget refreshes often and the COUNT
# only changes when a sim lands in the current month.
_USER_RUNS_THIS_MONTH_CACHE_TTL_S: int = 30
_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE: str = (
    "user-runs-this-month"
)

# Decision velocity - "how fast do you decide?" tile.
# 60s TTL: 2 cheap queries in the route, but the
# dashboard speed widget refreshes often.
_USER_DECISION_VELOCITY_CACHE_TTL_S: int = 60
_USER_DECISION_VELOCITY_CACHE_NAMESPACE: str = (
    "user-decision-velocity"
)

# Outcome velocity - "how fast do you record outcomes?"
# tile. 60s TTL: 2 cheap queries in the route.
_USER_OUTCOME_VELOCITY_CACHE_TTL_S: int = 60
_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE: str = (
    "user-outcome-velocity"
)

# Decision rate - "how many decisions per sim?" tile.
# 60s TTL: 2 cheap COUNTs in the route.
_USER_DECISION_RATE_CACHE_TTL_S: int = 60
_USER_DECISION_RATE_CACHE_NAMESPACE: str = (
    "user-decision-rate"
)

# Outcome rate - "how many outcomes per sim?" tile.
# 60s TTL: 2 cheap COUNTs in the route.
_USER_OUTCOME_RATE_CACHE_TTL_S: int = 60
_USER_OUTCOME_RATE_CACHE_NAMESPACE: str = (
    "user-outcome-rate"
)

# Decision-to-outcome delay - closes the loop on the
# decision->outcome chain. 60s TTL: 2 cheap queries in
# the route.
_USER_DECISION_TO_OUTCOME_DELAY_CACHE_TTL_S: int = 60
_USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE: str = (
    "user-decision-to-outcome-delay"
)

# Insights - executive summary. 60s TTL: the widget
# refreshes often and the underlying counts only
# change on a few write paths.
_USER_INSIGHTS_CACHE_TTL_S: int = 60
_USER_INSIGHTS_CACHE_NAMESPACE: str = "user-insights"

# Last-week stats - comparative stats. 60s TTL: 6
# cheap COUNTs in the route, but the trend chart
# refreshes often.
_USER_LAST_WEEK_STATS_CACHE_TTL_S: int = 60
_USER_LAST_WEEK_STATS_CACHE_NAMESPACE: str = (
    "user-last-week-stats"
)

# Projects needing attention - "which projects need a
# look?" tile. 60s TTL: the per-project loop is the
# heaviest user endpoint (5 queries × N projects).
_USER_PROJECTS_NEEDING_ATTENTION_CACHE_TTL_S: int = 60
_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE: str = (
    "user-projects-needing-attention"
)

# Sim failure rate - system-reliability widget.
# 60s TTL: 2 cheap COUNTs in the route.
_USER_SIM_FAILURE_RATE_CACHE_TTL_S: int = 60
_USER_SIM_FAILURE_RATE_CACHE_NAMESPACE: str = (
    "user-sim-failure-rate"
)

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


@router.post(
    "/me/clear-archive",
    response_model=MessageResponse,
    summary="Delete all projects owned by the current user",
    # Destructive — wipes every project (and its cascade) the user
    # owns. Cap path-spam at 5/min/IP so a runaway script or accidental
    # double-click can't blast through the user's entire archive.
    dependencies=[Depends(rate_limit(limit=5, window_s=60))],
)
def clear_archive(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete every project (and its cascade) owned by the authenticated user."""
    deleted = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    # Bust /me/dashboard so the next render reflects the
    # cleared project count + simulation count + decision
    # count + outcome count rather than waiting out the TTL.
    # Also bust /me/account-health: the health score
    # depends on every dim — sim/decision success ratios,
    # calibration MAE, blindspots — all of which shift
    # when the archive is wiped.
    cache_invalidate(
        namespace=_USER_DASHBOARD_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
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
        namespace=_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_TAG_TAXONOMY_CACHE_NAMESPACE,
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
        namespace=_USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE,
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
    # Coverage gaps + notifications depend on the user's
    # owned projects — wiping the archive would otherwise
    # leave stale data showing for up to the cache TTL.
    cache_invalidate(
        namespace=_USER_COVERAGE_GAPS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_NOTIFICATIONS_CACHE_NAMESPACE,
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
    return MessageResponse(message=f"Cleared {deleted} dossiers from your archive")


@router.get(
    "/me/export",
    summary="Export profile and dossiers as JSON",
    responses=_JSON_200,
)
def export_archive(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a JSON dump of the user's profile and dossiers."""
    projects = (
        db.query(Project).filter(Project.user_id == current_user.id).all()
    )

    def _project_row(p: Project) -> dict:
        return {
            "id": p.id,
            "title": getattr(p, "title", None),
            "description": getattr(p, "description", None),
            "status": getattr(p, "status", None),
            "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else None,
            "updated_at": p.updated_at.isoformat() if getattr(p, "updated_at", None) else None,
        }

    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "handle": current_user.handle,
            "tier": current_user.tier,
            "preferences": {
                "reduced_motion": current_user.reduced_motion,
                "email_notices": current_user.email_notices,
                "weekly_brief": current_user.weekly_brief,
                "default_units": current_user.default_units,
            },
            "cast_defaults": {
                "default_reader_count": current_user.default_reader_count,
                "default_scenario": current_user.default_scenario,
                "default_aov": current_user.default_aov,
                "keep_past_results": current_user.keep_past_results,
            },
        },
        "dossiers": [_project_row(p) for p in projects],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/me/accuracy-profile",
    summary="Per-user simulation accuracy and architect bias profile",
    responses=_JSON_200,
)
def get_accuracy_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profiles = db.execute(
        text("""
        SELECT architect_name, ema_delta, reliability_score, sample_count
        FROM user_claim_accuracy_profiles
        WHERE user_id=:uid AND sample_count >= 3 AND reliability_score >= 0.40
        ORDER BY reliability_score DESC
    """),
        {"uid": current_user.id},
    ).fetchall()

    history = db.execute(
        text("""
        SELECT simulation_id, predicted_conversion, actual_conversion, absolute_gap,
               signal_quality_at_run, accuracy_trend, created_at
        FROM user_simulation_accuracy_history
        WHERE user_id=:uid ORDER BY created_at ASC
    """),
        {"uid": current_user.id},
    ).fetchall()

    trend = history[-1].accuracy_trend if history else "INSUFFICIENT_DATA"
    gaps = [float(r.absolute_gap) for r in history if r.absolute_gap is not None]
    mean_gap = round(sum(gaps) / len(gaps), 4) if gaps else None

    return {
        "overall_accuracy_trend": trend,
        "simulations_with_outcomes": len(history),
        "mean_absolute_gap": mean_gap,
        "architect_biases": [
            {
                "architect": p.architect_name,
                "ema_delta": round(float(p.ema_delta), 4),
                "reliability": round(float(p.reliability_score), 4),
                "direction": "over-claims" if float(p.ema_delta) > 0 else "under-claims",
            }
            for p in profiles
        ],
        "gap_history": [
            {
                "simulation_id": r.simulation_id,
                "predicted": round(float(r.predicted_conversion), 4),
                "actual": round(float(r.actual_conversion), 4)
                if r.actual_conversion is not None
                else None,
                "gap": round(float(r.absolute_gap), 4) if r.absolute_gap is not None else None,
                "signal_quality": round(float(r.signal_quality_at_run), 4),
                "date": r.created_at.isoformat() if r.created_at else None,
            }
            for r in history
        ],
    }


@router.get(
    "/me/blindspots",
    summary="Detected market blindspots for the current user",
    responses=_JSON_200,
)
def get_blindspots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    rows = db.execute(
        text("""
        SELECT blindspot_type, blindspot_value, occurrence_count,
               first_seen, last_surfaced_to_user
        FROM user_market_blindspots
        WHERE user_id=:uid
          AND occurrence_count >= 2
          AND (last_surfaced_to_user IS NULL OR last_surfaced_to_user < :cutoff)
        ORDER BY occurrence_count DESC
    """),
        {"uid": current_user.id, "cutoff": cutoff},
    ).fetchall()

    DESCRIPTIONS = {
        "CLUSTER_IGNORED": (
            "You consistently overlook this customer segment despite strong fit signals"
        ),
        "ARCHITECT_UNCHALLENGED": (
            "You never question or vary this product attribute across simulations"
        ),
        "DIMENSION_MISSING": (
            "You consistently omit this market dimension (geography, age, or segment)"
        ),
        "COMPETITOR_IGNORED": (
            "You never include this competitive context in your simulations"
        ),
    }

    return {
        "blindspots": [
            {
                "type": r.blindspot_type,
                "value": r.blindspot_value,
                "occurrence_count": r.occurrence_count,
                "description": DESCRIPTIONS.get(
                    r.blindspot_type, "Recurring pattern detected"
                ),
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
            }
            for r in rows
        ]
    }


@router.get(
    "/me/dashboard",
    response_model=UserDashboardOut,
    summary=(
        "One-shot account snapshot — quota + project counts + "
        "calibration health + blindspots + narrative + signals"
    ),
    # Account page polls this; short TTL keeps the tile fresh
    # without hammering the DB on every render.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_my_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserDashboardOut:
    """Single-payload dashboard for the Account page.

    Composes account age, monthly sim quota, project / sim /
    decision / outcome counts, last-activity timestamp, calibration
    health, blindspot count, narrative, and key signals — all in
    one round-trip so the Account page doesn't fan out to
    /me/blindspots + the project list + the accuracy profile.

    Pure read-only — no Celery, no LLM.
    """
    # Cache hit → short-circuit the four queries. Key is namespaced
    # by user so one tenant never sees another's snapshot.
    cached = cache_get_json(
        namespace=_USER_DASHBOARD_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return UserDashboardOut(**cached)

    # ---- Tier + monthly quota ----------------------------------
    tier = (current_user.tier or "FREE").upper()

    # Count simulations created this calendar month for the
    # monthly-quota tile. Uses a single indexed SELECT — the
    # WHERE clause matches the enforcement layer's window.
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    monthly_sim_used = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(
                db.query(Project.id).filter(Project.user_id == current_user.id)
            ),
            Simulation.created_at >= month_start,
        )
        .count()
    )
    # Caps live in app.core.tier_enforcement. TIER_LIMITS is
    # keyed by lowercase tier name; fall back to the free tier
    # for any unknown label so the dashboard never 500s on a
    # misconfigured user.
    monthly_sim_cap = TIER_LIMITS.get(
        tier.lower(),
        TIER_LIMITS["free"],
    )["simulations_per_month"]

    # ---- Counts (single round-trip per entity) ------------------
    project_count = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .count()
    )
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if owned_project_ids:
        simulation_count = (
            db.query(Simulation)
            .filter(Simulation.project_id.in_(owned_project_ids))
            .count()
        )
        decision_count = (
            db.query(Decision)
            .filter(Decision.project_id.in_(owned_project_ids))
            .count()
        )
        outcome_count = (
            db.query(Outcome)
            .filter(Outcome.project_id.in_(owned_project_ids))
            .count()
        )
    else:
        simulation_count = 0
        decision_count = 0
        outcome_count = 0

    # ---- Last activity (newest created_at across the user's rows)
    last_activity_at: datetime | None = None
    for model_cls in (Project, Simulation, Decision, Outcome):
        last = (
            db.query(model_cls.created_at)
            .filter(
                (
                    model_cls.user_id == current_user.id
                    if hasattr(model_cls, "user_id")
                    else model_cls.project_id.in_(owned_project_ids)
                )
            )
            .order_by(model_cls.created_at.desc())
            .first()
        )
        if last and last[0]:
            if last_activity_at is None or last[0] > last_activity_at:
                last_activity_at = last[0]

    # ---- Calibration health (only if user has completed sims)
    calibration_health: dict | None = None
    if owned_project_ids:
        # Pull the sim id + the latest outcome's predicted /
        # actual rates so build_calibration_health can compute
        # real trend buckets instead of INSUFFICIENT_DATA.
        # Order by Outcome.created_at DESC so the LEFT JOIN's
        # newest outcome per sim is the first row we see per id.
        cal_rows = (
            db.query(
                Simulation.id,
                Simulation.created_at,
                Simulation.results_json,
                Outcome.predicted_conversion_rate,
                Outcome.actual_conversion_rate,
            )
            .outerjoin(
                Outcome, Outcome.simulation_id == Simulation.id,
            )
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .order_by(
                Simulation.id.asc(),
                Outcome.created_at.desc(),
            )
            .limit(200)
            .all()
        )
        # Dedupe to one row per Simulation.id (newest outcome
        # first per the ORDER BY above). Pass the real predicted
        # / actual pair to the helper — None,None would force
        # every trend bucket to INSUFFICIENT_DATA.
        seen_sids: set[int] = set()
        health_input: list[tuple] = []
        for r in cal_rows:
            if r.id in seen_sids:
                continue
            seen_sids.add(r.id)
            findings = (r.results_json or {}).get("domain_findings") or []
            health_input.append(
                (
                    r.created_at,
                    r.predicted_conversion_rate,
                    r.actual_conversion_rate,
                    findings,
                )
            )
        if health_input:
            calibration_health = build_calibration_health(health_input)

    # ---- Blindspot count (recent window) ------------------------
    blindspot_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    blindspot_count = (
        db.execute(
            text(
                """
            SELECT COUNT(*) FROM user_market_blindspots
            WHERE user_id = :uid AND occurrence_count >= 2
              AND (last_surfaced_to_user IS NULL
                   OR last_surfaced_to_user < :cutoff)
            """
            ),
            {"uid": current_user.id, "cutoff": blindspot_cutoff},
        ).scalar()
        or 0
    )

    # ---- Compose via the pure helper ----------------------------
    payload = build_user_dashboard(
        account_created_at=current_user.created_at,
        tier=tier,
        monthly_sim_used=monthly_sim_used,
        monthly_sim_cap=monthly_sim_cap,
        project_count=project_count,
        simulation_count=simulation_count,
        decision_count=decision_count,
        outcome_count=outcome_count,
        last_activity_at=last_activity_at,
        calibration_health=calibration_health,
        blindspot_count=int(blindspot_count),
    )

    cache_set_json(
        namespace=_USER_DASHBOARD_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_DASHBOARD_CACHE_TTL_S,
    )
    return UserDashboardOut(**payload)


@router.get(
    "/me/account-health",
    response_model=AccountHealthOut,
    summary=(
        "Single-payload qualitative account health verdict "
        "— 0-100 score + HEALTHY/NEEDS_ATTENTION/AT_RISK "
        "composed from MAE + blindspots + sim/decision "
        "success ratios + account age + penalties"
    ),
    # Read-only; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_account_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccountHealthOut:
    """Per-account qualitative health verdict.

    Composes a single big-number health score (0-100) plus
    a 3-bucket verdict from the same data slices that
    /me/dashboard surfaces quantitatively. Avoids the
    round-trip cost of /me/blindspots + /me/accuracy-profile
    + the project list + the outcomes digest for the home
    screen's "how am I doing?" tile.
    """
    # Cache hit → short-circuit.
    cached = cache_get_json(
        namespace=_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return AccountHealthOut(**cached)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    # ---- Sim success -------------------------------------------------
    sim_total = 0
    sim_completed = 0
    if owned_project_ids:
        sim_total = (
            db.query(Simulation)
            .filter(Simulation.project_id.in_(owned_project_ids))
            .count()
        )
        sim_completed = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .count()
        )

    # ---- Decision success --------------------------------------------
    dec_total = 0
    dec_completed = 0
    if owned_project_ids:
        dec_total = (
            db.query(Decision)
            .filter(Decision.project_id.in_(owned_project_ids))
            .count()
        )
        dec_completed = (
            db.query(Decision)
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.status == "COMPLETED",
            )
            .count()
        )

    # ---- MAE ---------------------------------------------------------
    mae: float | None = None
    critical_signal_count = 0
    if owned_project_ids:
        # Select Simulation.id so we can dedup by sim id (not
        # by object identity on created_at — the previous
        # ``id(r.created_at)`` key silently failed when two
        # sims shared a created_at second or when SQLAlchemy
        # reused the datetime instance across rows).
        # ORDER BY Outcome.created_at DESC so the newest
        # outcome per sim is the first row we encounter.
        health_rows = (
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
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .order_by(
                Simulation.id.asc(),
                Outcome.created_at.desc(),
            )
            .limit(200)
            .all()
        )
        # Dedupe per Simulation.id — first row per id wins
        # (newest outcome per the ORDER BY above).
        seen: set[int] = set()
        deduped: list[tuple] = []
        for r in health_rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            deduped.append(
                (r.created_at,
                 r.predicted_conversion_rate,
                 r.actual_conversion_rate,
                 (r.results_json or {}).get("domain_findings") or []),
            )
        # Filter to rows that actually have both values.
        usable = [
            (pred, act)
            for _, pred, act, _ in deduped
            if isinstance(pred, (int, float))
            and isinstance(act, (int, float))
        ]
        if usable:
            mae = sum(
                abs(act - pred) for pred, act in usable
            ) / len(usable)
        if deduped:
            try:
                health = build_calibration_health(deduped)
                # Count CRITICAL signals.
                for sig in (health or {}).get("key_signals", []):
                    if sig.get("severity") == "critical":
                        critical_signal_count += 1
            except Exception:
                pass

    # ---- Blindspot count --------------------------------------------
    blindspot_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    blindspot_count = (
        db.execute(
            text(
                """
            SELECT COUNT(*) FROM user_market_blindspots
            WHERE user_id = :uid AND occurrence_count >= 2
              AND (last_surfaced_to_user IS NULL
                   OR last_surfaced_to_user < :cutoff)
            """
            ),
            {"uid": current_user.id, "cutoff": blindspot_cutoff},
        ).scalar()
        or 0
    )

    # ---- Failed outcome count ---------------------------------------
    failed_outcome_count = 0
    if owned_project_ids:
        failed_outcome_count = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
                Outcome.calibration_score.is_(None),
            )
            .count()
        )

    # ---- Account age ------------------------------------------------
    account_age_days = 0
    if current_user.created_at is not None:
        ts = current_user.created_at
        delta = datetime.now(timezone.utc) - ts
        account_age_days = max(0, delta.days)

    payload = build_account_health(
        mae=mae,
        blindspot_count=int(blindspot_count),
        simulation_completed=sim_completed,
        simulation_total=sim_total,
        decision_completed=dec_completed,
        decision_total=dec_total,
        account_age_days=account_age_days,
        failed_outcome_count=failed_outcome_count,
        critical_signal_count=critical_signal_count,
    )

    cache_set_json(
        namespace=_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=60,
    )
    return AccountHealthOut(**payload)


@router.get(
    "/me/coverage-gaps",
    response_model=CoverageGapsOut,
    summary=(
        "Coverage gaps digest - surfaces dimensions the user "
        "has never explored (missing categories, no "
        "HIGH/CRITICAL sensitivity assumptions, thin cluster "
        "coverage)"
    ),
    # Read-only.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_coverage_gaps(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CoverageGapsOut:
    """Coverage gaps digest.

    Inverse of the portfolio-narrative: surfaces the
    dimensions the user has NEVER explored. Useful for
    nudging founders to broaden their inputs before
    trusting the next round of predictions.

    Bounded:
    - assumptions: all non-hidden rows across owned projects
    - clusters: distinct cluster IDs from cluster_breakdown
      across the user's completed sims
    """
    # Cache hit → short-circuit the SELECTs.
    cached = cache_get_json(
        namespace=_USER_COVERAGE_GAPS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return CoverageGapsOut(**cached)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    # All non-hidden assumptions across the user's projects.
    assumption_rows = []
    if owned_project_ids:
        assumption_rows = (
            db.query(Assumption)
            .filter(
                Assumption.project_id.in_(owned_project_ids),
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
        for a in assumption_rows
    ]

    # Distinct cluster IDs touched across COMPLETED sims.
    cluster_ids: set[int] = set()
    if owned_project_ids:
        results_rows = (
            db.query(Simulation.results_json)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .all()
        )
        for r in results_rows:
            breakdown = (r[0] or {}).get("cluster_breakdown") or {}
            for cid in breakdown.keys():
                try:
                    cluster_ids.add(int(cid))
                except (TypeError, ValueError):
                    continue

    payload = build_coverage_gaps(
        assumptions=assumption_dicts,
        cluster_ids=list(cluster_ids),
    )
    cache_set_json(
        namespace=_USER_COVERAGE_GAPS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_COVERAGE_GAPS_CACHE_TTL_S,
    )
    return CoverageGapsOut(**payload)


@router.get(
    "/me/notifications",
    response_model=NotificationsOut,
    summary=(
        "Single-payload inbox view - chronological list of "
        "blindspots + intervention quick wins + pending "
        "decisions + recent premortem criticals"
    ),
    # Read-only composition of multiple user-level slices.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationsOut:
    """Inbox feed.

    Composes a chronological (newest-first) feed of items
    that would warrant a founder's attention: blindspots
    flagged in the recent window, intervention quick wins,
    pending decisions, and recent premortem criticals.

    Avoids fanning out to /me/blindspots + the per-project
    decision/assumption/premortem endpoints for the
    home-screen inbox tile.
    """
    # Cache hit - short-circuit the two SELECTs.
    cached = cache_get_json(
        namespace=_USER_NOTIFICATIONS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return NotificationsOut(**cached)

    # ---- Blindspots ------------------------------------------------
    blindspot_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    bs_rows = db.execute(
        text(
            """
        SELECT blindspot_type, blindspot_value, occurrence_count,
               first_seen, last_surfaced_to_user
        FROM user_market_blindspots
        WHERE user_id = :uid AND occurrence_count >= 2
          AND (last_surfaced_to_user IS NULL
               OR last_surfaced_to_user < :cutoff)
        """
        ),
        {"uid": current_user.id, "cutoff": blindspot_cutoff},
    ).fetchall()
    blindspot_dicts = [
        {
            "blindspot_type": r.blindspot_type,
            "blindspot_value": r.blindspot_value,
            "occurrence_count": r.occurrence_count,
            "first_seen": r.first_seen,
            "last_surfaced_to_user": r.last_surfaced_to_user,
        }
        for r in bs_rows
    ]

    # ---- Pending decisions ----------------------------------------
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    pending_decision_dicts: list[dict] = []
    if owned_project_ids:
        decision_rows = (
            db.query(
                Decision.id,
                Decision.title,
                Decision.status,
                Decision.created_at,
            )
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.status.in_(("PENDING", "RUNNING")),
            )
            .order_by(Decision.created_at.desc())
            .limit(20)
            .all()
        )
        pending_decision_dicts = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in decision_rows
        ]

    payload = build_notifications(
        blindspots=blindspot_dicts,
        pending_decisions=pending_decision_dicts,
    )
    cache_set_json(
        namespace=_USER_NOTIFICATIONS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_NOTIFICATIONS_CACHE_TTL_S,
    )
    return NotificationsOut(**payload)


@router.get(
    "/me/weekly-digest",
    response_model=WeeklyDigestOut,
    summary=(
        "Weekly digest - rolling 7-day activity summary "
        "across all projects (sims, decisions, outcomes, "
        "calibration, quick wins, critical failures)"
    ),
    # Read-only; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_weekly_digest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WeeklyDigestOut:
    """Weekly digest.

    Composes a single rolling-7-day summary so the
    weekly email preview + the home-screen "this week"
    tile can render one paragraph + key signals without
    fanning out to /me/dashboard, /me/account-health, or
    the per-project endpoints.
    """
    # Cache hit - short-circuit the 4 COUNTs + the
    # cross-project iteration.
    cached = cache_get_json(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return WeeklyDigestOut(**cached)

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    # ---- Counts ----------------------------------------------------
    sim_count_week = 0
    decision_count_week = 0
    outcome_count_week = 0
    completed_sim_count_week = 0
    if owned_project_ids:
        sim_count_week = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= seven_days_ago,
            )
            .count()
        )
        completed_sim_count_week = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= seven_days_ago,
                Simulation.status == "COMPLETED",
            )
            .count()
        )
        decision_count_week = (
            db.query(Decision)
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.created_at >= seven_days_ago,
            )
            .count()
        )
        outcome_count_week = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
                Outcome.created_at >= seven_days_ago,
            )
            .count()
        )

    # ---- Calibration health for the rolling 7d window ----------
    calibration_health: dict | None = None
    if owned_project_ids:
        # Select Simulation.id so we can dedupe by sim id (not
        # by object identity on created_at — the previous
        # ``id(r.created_at)`` key silently failed when two
        # sims shared a created_at second or when SQLAlchemy
        # reused the datetime instance across rows).
        # ORDER BY Simulation.id ASC, Outcome.created_at DESC
        # so the newest outcome per sim is the first row we
        # encounter — the dedup below keeps that row.
        cal_rows = (
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
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
                Simulation.created_at >= seven_days_ago,
            )
            .order_by(
                Simulation.id.asc(),
                Outcome.created_at.desc(),
            )
            .limit(200)
            .all()
        )
        # Dedupe per Simulation.id — first row per id wins
        # (newest outcome per the ORDER BY above).
        seen: set[int] = set()
        deduped: list[tuple] = []
        for r in cal_rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            deduped.append(
                (
                    r.created_at,
                    r.predicted_conversion_rate,
                    r.actual_conversion_rate,
                    (r.results_json or {}).get(
                        "domain_findings"
                    ) or [],
                ),
            )
        if deduped:
            try:
                calibration_health = build_calibration_health(
                    deduped,
                )
            except Exception:
                calibration_health = None

    # ---- Cross-project rollups (quick wins + CRITICAL failures) -
    quick_wins_total = 0
    critical_failure_modes_total = 0
    if owned_project_ids:
        project_rows = (
            db.query(Project.interventions_json,
                     Project.premortem_json)
            .filter(Project.id.in_(owned_project_ids))
            .all()
        )
        for iv_json, pm_json in project_rows:
            if isinstance(iv_json, dict):
                iv_digest = build_intervention_digest(iv_json)
                quick_wins_total += iv_digest.get(
                    "quick_win_count", 0,
                )
            if isinstance(pm_json, dict):
                pm_digest = build_premortem_digest(pm_json)
                sev = pm_digest.get("severity_breakdown", {})
                critical_failure_modes_total += sev.get(
                    "CRITICAL", 0,
                )

    payload = build_weekly_digest(
        sim_count_week=sim_count_week,
        decision_count_week=decision_count_week,
        outcome_count_week=outcome_count_week,
        completed_sim_count_week=completed_sim_count_week,
        calibration_health=calibration_health,
        quick_wins_total=quick_wins_total,
        critical_failure_modes_total=critical_failure_modes_total,
    )
    cache_set_json(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_WEEKLY_DIGEST_CACHE_TTL_S,
    )
    return WeeklyDigestOut(**payload)


@router.get(
    "/me/digest-snapshot",
    response_model=DigestSnapshotOut,
    summary=(
        "Single-payload capture of all 5 user-level "
        "digests (dashboard + account_health + coverage_gaps "
        "+ notifications + weekly_digest) for archival or "
        "weekly-email snapshots"
    ),
    # Heavy composition - bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_digest_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DigestSnapshotOut:
    """All-user-levels-in-one snapshot.

    Composes the 5 user-level digests into a single
    payload suitable for archival comparison
    (week-over-week diffs) or weekly-email snapshots.
    No cache - the snapshot is supposed to capture the
    current state, not a TTL-delayed prior state.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    # Tier + monthly usage.
    tier = (current_user.tier or "FREE").upper()
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    monthly_sim_used = 0
    if owned_project_ids:
        monthly_sim_used = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= month_start,
            )
            .count()
        )
    monthly_sim_cap = TIER_LIMITS.get(
        tier.lower(),
        TIER_LIMITS["free"],
    )["simulations_per_month"]

    # Counts.
    project_count = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .count()
    )
    simulation_count = decision_count = outcome_count = 0
    if owned_project_ids:
        simulation_count = (
            db.query(Simulation)
            .filter(Simulation.project_id.in_(owned_project_ids))
            .count()
        )
        decision_count = (
            db.query(Decision)
            .filter(Decision.project_id.in_(owned_project_ids))
            .count()
        )
        outcome_count = (
            db.query(Outcome)
            .filter(Outcome.project_id.in_(owned_project_ids))
            .count()
        )

    dashboard = build_user_dashboard(
        account_created_at=current_user.created_at,
        tier=tier,
        monthly_sim_used=monthly_sim_used,
        monthly_sim_cap=monthly_sim_cap,
        project_count=project_count,
        simulation_count=simulation_count,
        decision_count=decision_count,
        outcome_count=outcome_count,
    )

    # Calibration MAE + critical signals for account_health.
    mae: float | None = None
    critical_signal_count = 0
    if owned_project_ids:
        # Select Simulation.id so we can dedupe by sim id (not
        # by object identity on created_at — the previous
        # ``id(r.created_at)`` key silently failed when two
        # sims shared a created_at second or when SQLAlchemy
        # reused the datetime instance across rows).
        # ORDER BY Simulation.id ASC, Outcome.created_at DESC
        # so the newest outcome per sim is the first row we
        # encounter — the dedup below keeps that row.
        health_rows = (
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
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .order_by(
                Simulation.id.asc(),
                Outcome.created_at.desc(),
            )
            .limit(200)
            .all()
        )
        seen: set[int] = set()
        deduped: list[tuple] = []
        for r in health_rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            deduped.append(
                (r.created_at,
                 r.predicted_conversion_rate,
                 r.actual_conversion_rate,
                 (r.results_json or {}).get(
                     "domain_findings"
                 ) or []),
            )
        usable = [
            (pred, act)
            for _, pred, act, _ in deduped
            if isinstance(pred, (int, float))
            and isinstance(act, (int, float))
        ]
        if usable:
            mae = sum(
                abs(act - pred) for pred, act in usable
            ) / len(usable)
        if deduped:
            try:
                cal = build_calibration_health(deduped)
                for sig in (cal or {}).get("key_signals", []):
                    if sig.get("severity") == "critical":
                        critical_signal_count += 1
            except Exception:
                pass

    blindspot_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    blindspot_count = (
        db.execute(
            text(
                """SELECT COUNT(*) FROM user_market_blindspots
                   WHERE user_id = :uid AND occurrence_count >= 2
                     AND (last_surfaced_to_user IS NULL
                          OR last_surfaced_to_user < :cutoff)"""
            ),
            {"uid": current_user.id, "cutoff": blindspot_cutoff},
        ).scalar()
        or 0
    )

    account_age_days = 0
    if current_user.created_at is not None:
        delta = datetime.now(timezone.utc) - current_user.created_at
        account_age_days = max(0, delta.days)

    failed_outcome_count = 0
    if owned_project_ids:
        failed_outcome_count = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
                Outcome.calibration_score.is_(None),
            )
            .count()
        )

    account_health = build_account_health(
        mae=mae,
        blindspot_count=int(blindspot_count),
        simulation_completed=simulation_count,  # proxy
        simulation_total=simulation_count,
        decision_completed=decision_count,
        decision_total=decision_count,
        account_age_days=account_age_days,
        failed_outcome_count=failed_outcome_count,
        critical_signal_count=critical_signal_count,
    )

    # coverage_gaps
    assumption_dicts = []
    covered_clusters: set[int] = set()
    if owned_project_ids:
        assumption_rows = (
            db.query(Assumption)
            .filter(
                Assumption.project_id.in_(owned_project_ids),
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
            for a in assumption_rows
        ]
        # cluster ids from completed sims
        results_rows = (
            db.query(Simulation.results_json)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.status == "COMPLETED",
            )
            .all()
        )
        for r in results_rows:
            bd = (r[0] or {}).get("cluster_breakdown") or {}
            for cid in bd.keys():
                try:
                    covered_clusters.add(int(cid))
                except (TypeError, ValueError):
                    continue
    coverage_gaps = build_coverage_gaps(
        assumptions=assumption_dicts,
        cluster_ids=list(covered_clusters),
    )

    # notifications (blindspots + pending decisions)
    bs_rows = db.execute(
        text(
            """SELECT blindspot_type, blindspot_value,
                      occurrence_count, first_seen,
                      last_surfaced_to_user
               FROM user_market_blindspots
               WHERE user_id = :uid AND occurrence_count >= 2
                 AND (last_surfaced_to_user IS NULL
                      OR last_surfaced_to_user < :cutoff)"""
        ),
        {"uid": current_user.id, "cutoff": blindspot_cutoff},
    ).fetchall()
    blindspot_dicts = [
        {
            "blindspot_type": r.blindspot_type,
            "blindspot_value": r.blindspot_value,
            "occurrence_count": r.occurrence_count,
            "first_seen": r.first_seen,
            "last_surfaced_to_user": r.last_surfaced_to_user,
        }
        for r in bs_rows
    ]
    pending_decision_dicts: list[dict] = []
    if owned_project_ids:
        decision_rows = (
            db.query(
                Decision.id,
                Decision.title,
                Decision.status,
                Decision.created_at,
            )
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.status.in_(("PENDING", "RUNNING")),
            )
            .order_by(Decision.created_at.desc())
            .limit(20)
            .all()
        )
        pending_decision_dicts = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in decision_rows
        ]
    notifications = build_notifications(
        blindspots=blindspot_dicts,
        pending_decisions=pending_decision_dicts,
    )

    # weekly_digest (last 7d)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    sim_count_week = completed_sim_count_week = (
        decision_count_week
    ) = outcome_count_week = 0
    if owned_project_ids:
        sim_count_week = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= seven_days_ago,
            )
            .count()
        )
        completed_sim_count_week = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= seven_days_ago,
                Simulation.status == "COMPLETED",
            )
            .count()
        )
        decision_count_week = (
            db.query(Decision)
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.created_at >= seven_days_ago,
            )
            .count()
        )
        outcome_count_week = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
                Outcome.created_at >= seven_days_ago,
            )
            .count()
        )
    weekly_digest = build_weekly_digest(
        sim_count_week=sim_count_week,
        decision_count_week=decision_count_week,
        outcome_count_week=outcome_count_week,
        completed_sim_count_week=completed_sim_count_week,
    )

    payload = build_digest_snapshot(
        dashboard=dashboard,
        account_health=account_health,
        coverage_gaps=coverage_gaps,
        notifications=notifications,
        weekly_digest=weekly_digest,
    )
    return DigestSnapshotOut(**payload)


@router.get(
    "/me/projects-summary",
    response_model=ProjectsSummaryOut,
    summary=(
        "Lightweight per-project summary cards for the "
        "dashboard's projects-list grid view"
    ),
    # Read-only composition; bounded by MAX_PROJECTS.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_projects_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectsSummaryOut:
    """Per-project summary cards.

    For each owned project, returns just the fields the
    dashboard's grid view needs (id, title, status, brief
    completed, latest sim conversion rate + status + count,
    sim/decision/outcome totals). Avoids sending full
    ProjectOut payloads (descriptions, tags, briefs) when
    the dashboard just needs a thumbnail.
    """
    # Cache hit - short-circuit the 4 batch queries.
    cached = cache_get_json(
        namespace=_USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectsSummaryOut(**cached)

    # One SELECT for the basic project listing + brief
    # completion flag.
    project_rows = (
        db.query(
            Project.id,
            Project.title,
            Project.status,
            Project.brief_completed_at,
        )
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    if not project_rows:
        return ProjectsSummaryOut()

    # Latest sim per project via a single subquery.
    latest_sim_subq = (
        db.query(
            Simulation.project_id,
            Simulation.status,
            Simulation.predicted_conversion_rate,
            Simulation.created_at,
        )
        .filter(
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .subquery()
    )

    # Count sims/decisions/outcomes per project (3
    # separate GROUP BY queries).
    from sqlalchemy import func as _sqlfunc

    sim_counts = dict(
        db.query(
            Simulation.project_id,
            _sqlfunc.count(Simulation.id),
        )
        .filter(
            Simulation.project_id.in_(
                p.id for p in project_rows
            ),
        )
        .group_by(Simulation.project_id)
        .all()
    )
    decision_counts = dict(
        db.query(
            Decision.project_id,
            _sqlfunc.count(Decision.id),
        )
        .filter(
            Decision.project_id.in_(
                p.id for p in project_rows
            ),
        )
        .group_by(Decision.project_id)
        .all()
    )
    outcome_counts = dict(
        db.query(
            Outcome.project_id,
            _sqlfunc.count(Outcome.id),
        )
        .filter(
            Outcome.project_id.in_(
                p.id for p in project_rows
            ),
        )
        .group_by(Outcome.project_id)
        .all()
    )

    # Latest completed sim per project.
    latest_sim_rows = (
        db.query(latest_sim_subq)
        .all()
    )
    latest_sim_by_project: dict[int, object] = {}
    for r in latest_sim_rows:
        latest_sim_by_project[r.project_id] = r

    summaries: list[dict] = []
    for p in project_rows:
        ls = latest_sim_by_project.get(p.id)
        summaries.append({
            "id": p.id,
            "title": p.title,
            "status": p.status,
            "brief_completed": p.brief_completed_at is not None,
            "latest_sim_conversion_rate": (
                ls.predicted_conversion_rate if ls else None
            ),
            "latest_sim_status": ls.status if ls else None,
            "latest_sim_created_at": (
                ls.created_at if ls else None
            ),
            "sim_count": sim_counts.get(p.id, 0),
            "decision_count": decision_counts.get(p.id, 0),
            "outcome_count": outcome_counts.get(p.id, 0),
        })

    payload = build_projects_summary(summaries)
    cache_set_json(
        namespace=_USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_PROJECTS_SUMMARY_CACHE_TTL_S,
    )
    return ProjectsSummaryOut(**payload)


@router.get(
    "/me/usage-by-week",
    response_model=UsageByWeekOut,
    summary=(
        "Weekly volume history - per-week sim / decision / "
        "outcome counts for the last 12 weeks so the "
        "dashboard can render a usage-over-time chart"
    ),
    # Read-only; bounded by MAX_WEEKS.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_usage_by_week(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UsageByWeekOut:
    """Weekly usage history.

    Builds 12 week-buckets (oldest first) over the last 12
    calendar weeks and counts sims / decisions / outcomes
    per week. Output is suitable for a usage-over-time
    bar chart on the dashboard.
    """
    from app.simulation.usage_by_week import (
        MAX_WEEKS as _UBW_MAX,
    )
    from sqlalchemy import func as _sqlfunc

    # Cache hit - short-circuit the 3 GROUP BY queries.
    cached = cache_get_json(
        namespace=_USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return UsageByWeekOut(**cached)

    today = datetime.now(timezone.utc).date()
    # Week starts: weeks 11, 10, ..., 0 (oldest first).
    week_starts: list = []
    for w in range(_UBW_MAX - 1, -1, -1):
        ref = today - timedelta(days=today.weekday(), weeks=w)
        week_starts.append(ref)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return UsageByWeekOut(
            weeks=[
                {
                    "week_start": ws.isoformat(),
                    "sim_count": 0,
                    "decision_count": 0,
                    "outcome_count": 0,
                }
                for ws in week_starts
            ],
        )

    earliest = datetime.combine(
        week_starts[0], datetime.min.time(),
        tzinfo=timezone.utc,
    )

    # Per-week sim + outcome counts in a single batch via
    # GROUP BY on the date_trunc('week', ...).
    raw_sim_rows = (
        db.query(
            _sqlfunc.date_trunc(
                "week", Simulation.created_at,
            ).label("week_start"),
            _sqlfunc.count(Simulation.id).label("sim_count"),
        )
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.created_at >= earliest,
        )
        .group_by("week_start")
        .all()
    )
    raw_outcome_rows = (
        db.query(
            _sqlfunc.date_trunc(
                "week", Outcome.created_at,
            ).label("week_start"),
            _sqlfunc.count(Outcome.id).label("outcome_count"),
        )
        .filter(
            Outcome.project_id.in_(owned_project_ids),
            Outcome.created_at >= earliest,
        )
        .group_by("week_start")
        .all()
    )
    raw_decision_rows = (
        db.query(
            _sqlfunc.date_trunc(
                "week", Decision.created_at,
            ).label("week_start"),
            _sqlfunc.count(Decision.id).label("decision_count"),
        )
        .filter(
            Decision.project_id.in_(owned_project_ids),
            Decision.created_at >= earliest,
        )
        .group_by("week_start")
        .all()
    )

    sim_by_week = {
        r.week_start.date().isoformat(): r.sim_count
        for r in raw_sim_rows
    }
    decision_by_week = {
        r.week_start.date().isoformat(): r.decision_count
        for r in raw_decision_rows
    }
    outcome_by_week = {
        r.week_start.date().isoformat(): r.outcome_count
        for r in raw_outcome_rows
    }

    week_buckets = [
        {
            "week_start": ws.isoformat(),
            "sim_count": sim_by_week.get(ws.isoformat(), 0),
            "decision_count": (
                decision_by_week.get(ws.isoformat(), 0)
            ),
            "outcome_count": outcome_by_week.get(
                ws.isoformat(), 0,
            ),
        }
        for ws in week_starts
    ]
    payload = build_usage_by_week(week_buckets)
    cache_set_json(
        namespace=_USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_USAGE_BY_WEEK_CACHE_TTL_S,
    )
    return UsageByWeekOut(**payload)


@router.get(
    "/me/projects-by-status",
    response_model=ProjectsByStatusOut,
    summary=(
        "Per-user project status breakdown - count of "
        "projects per status for the dashboard's pie chart"
    ),
    # Read-only; bounded by project count.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_projects_by_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectsByStatusOut:
    """Project status breakdown.

    Single GROUP BY query that returns (status, count)
    pairs for the user's projects, plus an actionable
    count (PENDING + RUNNING). Useful for the pie-chart
    widget on the home screen.
    """
    from sqlalchemy import func as _sqlfunc

    # Cache hit - short-circuit the GROUP BY.
    cached = cache_get_json(
        namespace=_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectsByStatusOut(**cached)

    rows = (
        db.query(Project.status, _sqlfunc.count(Project.id))
        .filter(Project.user_id == current_user.id)
        .group_by(Project.status)
        .all()
    )
    payload = build_projects_by_status(
        status_counts=[(r[0], r[1]) for r in rows],
    )
    cache_set_json(
        namespace=_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_PROJECTS_BY_STATUS_CACHE_TTL_S,
    )
    return ProjectsByStatusOut(**payload)


@router.get(
    "/me/tag-taxonomy",
    response_model=TagTaxonomyOut,
    summary=(
        "Per-user tag taxonomy - distinct tags with "
        "project counts for the dashboard's tag-filter "
        "dropdowns"
    ),
    # Read-only composition; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_tag_taxonomy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagTaxonomyOut:
    """Tag taxonomy.

    For each owned project, flattens ``Project.tags`` (a
    list) into one row per (project, tag), then groups by
    tag to compute the count. Useful for tag-filter
    dropdowns that need a current tag list.
    """
    # Cache hit - short-circuit the JSONB unnest + GROUP BY.
    cached = cache_get_json(
        namespace=_USER_TAG_TAXONOMY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return TagTaxonomyOut(**cached)

    # Single SELECT that flattens tags to one row per
    # (tag, project_id) pair via JSONB unnest.
    rows = db.execute(
        text(
            """
        SELECT tag, COUNT(*) AS project_count
        FROM projects,
             jsonb_array_elements_text(
                 CASE WHEN jsonb_typeof(tags) = 'array'
                      THEN tags
                      ELSE '[]'::jsonb
                 END
             ) AS tag
        WHERE user_id = :uid
        GROUP BY tag
        ORDER BY project_count DESC, tag ASC
        """
        ),
        {"uid": current_user.id},
    ).fetchall()
    payload = build_tag_taxonomy(
        tag_counts=[(r[0], r[1]) for r in rows],
    )
    cache_set_json(
        namespace=_USER_TAG_TAXONOMY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_TAG_TAXONOMY_CACHE_TTL_S,
    )
    return TagTaxonomyOut(**payload)


@router.get(
    "/me/most-active-project",
    response_model=MostActiveProjectOut,
    summary=(
        "Per-user most-active project in the last 7 days - "
        "the project with the most sim + decision + outcome "
        "activity, surfaced as a 'focus here next' "
        "recommendation"
    ),
    # Read-only; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_most_active_project(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MostActiveProjectOut:
    """Most-active project.

    For each owned project, sums sims + decisions +
    outcomes in the last 7 days and returns the project
    with the highest total. Useful for the dashboard's
    'where should I focus?' tile.
    """
    from sqlalchemy import func as _sqlfunc

    # Cache hit - short-circuit the 3 GROUP BYs.
    cached = cache_get_json(
        namespace=_USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return MostActiveProjectOut(**cached)

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return MostActiveProjectOut(
            narrative="No projects on file yet.",
        )

    # Sim count per project (last 7d).
    sim_counts_rows = (
        db.query(
            Simulation.project_id,
            _sqlfunc.count(Simulation.id).label("sim_count"),
        )
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.created_at >= seven_days_ago,
        )
        .group_by(Simulation.project_id)
        .all()
    )
    decision_counts_rows = (
        db.query(
            Decision.project_id,
            _sqlfunc.count(Decision.id).label("decision_count"),
        )
        .filter(
            Decision.project_id.in_(owned_project_ids),
            Decision.created_at >= seven_days_ago,
        )
        .group_by(Decision.project_id)
        .all()
    )
    outcome_counts_rows = (
        db.query(
            Outcome.project_id,
            _sqlfunc.count(Outcome.id).label("outcome_count"),
        )
        .filter(
            Outcome.project_id.in_(owned_project_ids),
            Outcome.created_at >= seven_days_ago,
        )
        .group_by(Outcome.project_id)
        .all()
    )

    sim_by_pid = {r.project_id: r.sim_count for r in sim_counts_rows}
    dec_by_pid = {
        r.project_id: r.decision_count
        for r in decision_counts_rows
    }
    out_by_pid = {
        r.project_id: r.outcome_count
        for r in outcome_counts_rows
    }

    # Project titles.
    project_rows = (
        db.query(Project.id, Project.title)
        .filter(Project.id.in_(owned_project_ids))
        .all()
    )
    title_by_pid = {r.id: r.title for r in project_rows}

    # 5-tuple per project: (id, title, sim, dec, out).
    activity = [
        (
            pid,
            title_by_pid.get(pid, ""),
            sim_by_pid.get(pid, 0),
            dec_by_pid.get(pid, 0),
            out_by_pid.get(pid, 0),
        )
        for pid in owned_project_ids
    ]
    payload = build_most_active_project(project_activity=activity)
    cache_set_json(
        namespace=_USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_MOST_ACTIVE_PROJECT_CACHE_TTL_S,
    )
    return MostActiveProjectOut(**payload)


@router.get(
    "/me/quick-stats",
    response_model=QuickStatsOut,
    summary=(
        "Per-user minimal one-liner stats for mobile "
        "widgets + sidebars - just project / sim / decision / "
        "outcome totals + account age"
    ),
    # Read-only; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_quick_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuickStatsOut:
    """Quick stats.

    Minimal "one-liner" account summary for mobile
    widgets + sidebars. 4 cheap COUNTs + the
    ``current_user.created_at`` timestamp.
    """
    # Cache hit - short-circuit the 4 COUNTs.
    cached = cache_get_json(
        namespace=_USER_QUICK_STATS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return QuickStatsOut(**cached)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    total_projects = len(owned_project_ids)
    total_simulations = 0
    total_decisions = 0
    total_outcomes = 0
    if owned_project_ids:
        total_simulations = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
            )
            .count()
        )
        total_decisions = (
            db.query(Decision)
            .filter(
                Decision.project_id.in_(owned_project_ids),
            )
            .count()
        )
        total_outcomes = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
            )
            .count()
        )

    account_age_days = 0
    if current_user.created_at is not None:
        ts = current_user.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        account_age_days = max(0, delta.days)

    payload = build_quick_stats(
        total_projects=total_projects,
        total_simulations=total_simulations,
        total_decisions=total_decisions,
        total_outcomes=total_outcomes,
        account_age_days=account_age_days,
    )
    cache_set_json(
        namespace=_USER_QUICK_STATS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_QUICK_STATS_CACHE_TTL_S,
    )
    return QuickStatsOut(**payload)


@router.get(
    "/me/portfolio-health-snapshot",
    response_model=PortfolioHealthSnapshotOut,
    summary=(
        "Per-user portfolio health rollup - 0-100 average "
        "score across all of the user's projects so the "
        "dashboard header can surface one big number"
    ),
    # Read-only; per-project rollup.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_portfolio_health_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioHealthSnapshotOut:
    """Portfolio health snapshot.

    Composes a single 0-100 portfolio health rollup so
    the dashboard header can surface one big number
    without fanning out to every per-project
    ``/projects/{id}/health`` endpoint.
    """
    from app.simulation.project_health import build_project_health

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return PortfolioHealthSnapshotOut(
            narrative="No projects on file yet.",
        )

    # Cache hit - short-circuit the per-project loop.
    cached = cache_get_json(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return PortfolioHealthSnapshotOut(**cached)

    # Per-project rollup. For each owned project, pull
    # the inputs the project-health helper needs (latest
    # sim confidence, critical-finding count, pending
    # decision count, weak-link count, outcome presence)
    # and call build_project_health inline.

    payloads: list[dict] = []
    for pid in owned_project_ids:
        project = (
            db.query(Project)
            .filter(Project.id == pid)
            .first()
        )
        if project is None:
            continue

        latest_completed_sim = (
            db.query(Simulation)
            .filter(
                Simulation.project_id == pid,
                Simulation.status == "COMPLETED",
            )
            .order_by(Simulation.created_at.desc())
            .first()
        )
        sim_confidence: float | None = None
        critical_finding_count = 0
        if latest_completed_sim is not None:
            sim_confidence = getattr(
                latest_completed_sim, "confidence_score", None,
            )
            if sim_confidence is not None:
                sim_confidence = float(sim_confidence) / 100.0
            for f in (latest_completed_sim.results_json or {}).get(
                "domain_findings", []
            ) or []:
                if isinstance(f, dict) and (
                    f.get("severity") == "CRITICAL"
                    or f.get("level") == "CRITICAL"
                ):
                    critical_finding_count += 1

        pending_decision_count = (
            db.query(Decision)
            .filter(
                Decision.project_id == pid,
                Decision.status.in_(("PENDING", "RUNNING")),
            )
            .count()
        )

        weak_link_count = 0
        assumption_count = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == pid,
                Assumption.is_hidden.is_(False),
            )
            .count()
        )
        if assumption_count:
            from app.simulation.assumption_digest import (
                build_assumption_digest,
            )
            assumption_rows = (
                db.query(Assumption)
                .filter(
                    Assumption.project_id == pid,
                    Assumption.is_hidden.is_(False),
                )
                .all()
            )
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

        has_outcome = (
            db.query(Outcome.id)
            .filter(Outcome.project_id == pid)
            .first()
            is not None
        )

        payloads.append(build_project_health(
            sim_confidence=sim_confidence,
            critical_finding_count=critical_finding_count,
            pending_decision_count=pending_decision_count,
            weak_link_count=weak_link_count,
            has_outcome=has_outcome,
        ))

    payload = build_portfolio_health_snapshot(
        project_health_payloads=payloads,
    )
    cache_set_json(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_TTL_S,
    )
    return PortfolioHealthSnapshotOut(**payload)


@router.get(
    "/me/last-touched-project",
    response_model=LastTouchedProjectOut,
    summary=(
        "Per-user last-touched project - the most-recent "
        "activity (sim / decision / outcome) across the "
        "user's projects, surfaced as a 'where was I "
        "last?' recommendation"
    ),
    # Read-only; 3 cheap MAX-by-id queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_last_touched_project(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LastTouchedProjectOut:
    """Last-touched project.

    Picks the most recent (sim / decision / outcome) row
    across the user's projects and surfaces the owning
    project as the 'where was I last?' answer.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return LastTouchedProjectOut()

    # Cache hit - short-circuit the 3 MAX-by-id queries.
    cached = cache_get_json(
        namespace=_USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return LastTouchedProjectOut(**cached)

    # Latest sim per project.
    sim_rows = (
        db.query(
            Simulation.id,
            Simulation.project_id,
            Simulation.created_at,
        )
        .filter(Simulation.project_id.in_(owned_project_ids))
        .order_by(Simulation.id.desc())
        .limit(50)
        .all()
    )
    # Latest decision per project.
    decision_rows = (
        db.query(
            Decision.id,
            Decision.project_id,
            Decision.created_at,
        )
        .filter(Decision.project_id.in_(owned_project_ids))
        .order_by(Decision.id.desc())
        .limit(50)
        .all()
    )
    # Latest outcome per project.
    outcome_rows = (
        db.query(
            Outcome.id,
            Outcome.project_id,
            Outcome.created_at,
        )
        .filter(Outcome.project_id.in_(owned_project_ids))
        .order_by(Outcome.id.desc())
        .limit(50)
        .all()
    )

    # Project titles.
    project_rows = (
        db.query(Project.id, Project.title)
        .filter(Project.id.in_(owned_project_ids))
        .all()
    )
    title_by_pid = {r.id: r.title for r in project_rows}

    activity_rows: list[dict] = []
    for s in sim_rows:
        activity_rows.append({
            "project_id": s.project_id,
            "project_title": title_by_pid.get(s.project_id, ""),
            "activity_type": "sim",
            "activity_at": s.created_at,
        })
    for d in decision_rows:
        activity_rows.append({
            "project_id": d.project_id,
            "project_title": title_by_pid.get(d.project_id, ""),
            "activity_type": "decision",
            "activity_at": d.created_at,
        })
    for o in outcome_rows:
        activity_rows.append({
            "project_id": o.project_id,
            "project_title": title_by_pid.get(o.project_id, ""),
            "activity_type": "outcome",
            "activity_at": o.created_at,
        })

    payload = build_last_touched_project(
        activity_rows=activity_rows,
    )
    cache_set_json(
        namespace=_USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_LAST_TOUCHED_PROJECT_CACHE_TTL_S,
    )
    return LastTouchedProjectOut(**payload)


@router.get(
    "/me/runs-this-month",
    response_model=RunsThisMonthOut,
    summary=(
        "Per-user runs-this-month - tiny integer payload "
        "for the dashboard's tier-quota widget: count of "
        "sims created this calendar month + tier cap + "
        "remaining"
    ),
    # Read-only; 1 cheap COUNT.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_runs_this_month(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RunsThisMonthOut:
    """Runs-this-month.

    Single COUNT query for the sims created this calendar
    month across the user's projects. The tier cap comes
    from TIER_LIMITS so the widget can show
    '5/50 sims this month'.
    """
    # Cache hit - short-circuit the COUNT.
    cached = cache_get_json(
        namespace=_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return RunsThisMonthOut(**cached)

    tier = (current_user.tier or "FREE").upper()
    monthly_cap = TIER_LIMITS.get(
        tier.lower(), TIER_LIMITS["free"],
    )["simulations_per_month"]

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    runs_this_month = 0
    if owned_project_ids:
        runs_this_month = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= month_start,
            )
            .count()
        )

    payload = build_runs_this_month(
        runs_this_month=runs_this_month,
        monthly_cap=monthly_cap,
        tier=tier,
    )
    cache_set_json(
        namespace=_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_RUNS_THIS_MONTH_CACHE_TTL_S,
    )
    return RunsThisMonthOut(**payload)


@router.get(
    "/me/decision-velocity",
    response_model=DecisionVelocityOut,
    summary=(
        "Per-user decision velocity - average gap between a "
        "completed sim and the user's first decision on "
        "that project"
    ),
    # Read-only; 2 cheap queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_decision_velocity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionVelocityOut:
    """Decision velocity.

    For each owned project with a COMPLETED sim and a
    decision, computes the gap (in hours) between sim
    completion and the earliest decision on that project.
    Returns the average + median + fastest + slowest
    across the user's portfolio.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return DecisionVelocityOut()

    # Cache hit - short-circuit the 2 queries.
    cached = cache_get_json(
        namespace=_USER_DECISION_VELOCITY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return DecisionVelocityOut(**cached)

    # Latest completed sim per project.
    sim_rows = (
        db.query(
            Simulation.project_id,
            Simulation.created_at,
        )
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.id.desc())
        .all()
    )
    sim_completed_by_pid: dict[int, object] = {}
    for s in sim_rows:
        if s.project_id not in sim_completed_by_pid:
            sim_completed_by_pid[s.project_id] = s.created_at

    # Earliest decision per project.
    decision_rows = (
        db.query(
            Decision.project_id,
            Decision.created_at,
        )
        .filter(Decision.project_id.in_(owned_project_ids))
        .order_by(Decision.id.asc())
        .all()
    )
    first_decision_by_pid: dict[int, object] = {}
    for d in decision_rows:
        if d.project_id not in first_decision_by_pid:
            first_decision_by_pid[d.project_id] = d.created_at

    pairs: list[tuple] = []
    for pid in owned_project_ids:
        sim_dt = sim_completed_by_pid.get(pid)
        dec_dt = first_decision_by_pid.get(pid)
        if sim_dt and dec_dt:
            pairs.append((sim_dt, dec_dt))

    payload = build_decision_velocity(sim_decision_pairs=pairs)
    cache_set_json(
        namespace=_USER_DECISION_VELOCITY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_DECISION_VELOCITY_CACHE_TTL_S,
    )
    return DecisionVelocityOut(**payload)


@router.get(
    "/me/outcome-velocity",
    response_model=OutcomeVelocityOut,
    summary=(
        "Per-user outcome velocity - average gap between a "
        "completed sim and the user's first outcome on that "
        "project"
    ),
    # Read-only; 2 cheap queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_outcome_velocity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeVelocityOut:
    """Outcome velocity.

    For each owned project with a COMPLETED sim and an
    outcome, computes the gap (in hours) between sim
    completion and the earliest outcome on that project.
    Returns the average + median + fastest + slowest
    across the user's portfolio.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return OutcomeVelocityOut()

    # Cache hit - short-circuit the 2 queries.
    cached = cache_get_json(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return OutcomeVelocityOut(**cached)

    # Latest completed sim per project.
    sim_rows = (
        db.query(
            Simulation.project_id,
            Simulation.created_at,
        )
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.id.desc())
        .all()
    )
    sim_completed_by_pid: dict[int, object] = {}
    for s in sim_rows:
        if s.project_id not in sim_completed_by_pid:
            sim_completed_by_pid[s.project_id] = s.created_at

    # Earliest outcome per project.
    outcome_rows = (
        db.query(
            Outcome.project_id,
            Outcome.created_at,
        )
        .filter(Outcome.project_id.in_(owned_project_ids))
        .order_by(Outcome.id.asc())
        .all()
    )
    first_outcome_by_pid: dict[int, object] = {}
    for o in outcome_rows:
        if o.project_id not in first_outcome_by_pid:
            first_outcome_by_pid[o.project_id] = o.created_at

    pairs: list[tuple] = []
    for pid in owned_project_ids:
        sim_dt = sim_completed_by_pid.get(pid)
        out_dt = first_outcome_by_pid.get(pid)
        if sim_dt and out_dt:
            pairs.append((sim_dt, out_dt))

    payload = build_outcome_velocity(sim_outcome_pairs=pairs)
    cache_set_json(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_OUTCOME_VELOCITY_CACHE_TTL_S,
    )
    return OutcomeVelocityOut(**payload)


@router.get(
    "/me/decision-rate",
    response_model=DecisionRateOut,
    summary=(
        "Per-user decision utilization rate - decisions "
        "per completed sim across the portfolio"
    ),
    # Read-only; 2 cheap COUNTs.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_decision_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionRateOut:
    """Decision rate.

    Computes total decisions / total completed sims
    across the user's portfolio. Useful for the
    dashboard's "decision utilization" widget.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return DecisionRateOut(
            narrative="No projects on file yet.",
        )

    # Cache hit - short-circuit the 2 COUNTs.
    cached = cache_get_json(
        namespace=_USER_DECISION_RATE_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return DecisionRateOut(**cached)

    sim_count = (
        )

    sim_count = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.status == "COMPLETED",
        )
        .count()
    )
    decision_count = (
        db.query(Decision)
        .filter(Decision.project_id.in_(owned_project_ids))
        .count()
    )

    payload = build_decision_rate(
        sim_count=sim_count,
        decision_count=decision_count,
    )
    cache_set_json(
        namespace=_USER_DECISION_RATE_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_DECISION_RATE_CACHE_TTL_S,
    )
    return DecisionRateOut(**payload)


@router.get(
    "/me/outcome-rate",
    response_model=OutcomeRateOut,
    summary=(
        "Per-user outcome coverage rate - outcomes per "
        "completed sim across the portfolio"
    ),
    # Read-only; 2 cheap COUNTs.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_outcome_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeRateOut:
    """Outcome rate.

    Computes total outcomes / total completed sims
    across the user's portfolio. Analog of
    /me/decision-rate but for outcomes.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return OutcomeRateOut(
            narrative="No projects on file yet.",
        )

    # Cache hit - short-circuit the 2 COUNTs.
    cached = cache_get_json(
        namespace=_USER_OUTCOME_RATE_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return OutcomeRateOut(**cached)

    sim_count = (
        )

    sim_count = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.status == "COMPLETED",
        )
        .count()
    )
    outcome_count = (
        db.query(Outcome)
        .filter(Outcome.project_id.in_(owned_project_ids))
        .count()
    )

    payload = build_outcome_rate(
        sim_count=sim_count,
        outcome_count=outcome_count,
    )
    cache_set_json(
        namespace=_USER_OUTCOME_RATE_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_OUTCOME_RATE_CACHE_TTL_S,
    )
    return OutcomeRateOut(**payload)


@router.get(
    "/me/decision-to-outcome-delay",
    response_model=DecisionToOutcomeDelayOut,
    summary=(
        "Per-user decision->outcome loop time - average "
        "gap between a decision and the user's next outcome "
        "on the same project. Closes the decision->outcome "
        "chain."
    ),
    # Read-only; 2 cheap queries.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_decision_to_outcome_delay(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionToOutcomeDelayOut:
    """Decision-to-outcome delay.

    For each owned project, computes the gap (in hours)
    between each decision and the next outcome on that
    project. Returns the average + median + fastest +
    slowest across the user's portfolio.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return DecisionToOutcomeDelayOut()

    # Cache hit - short-circuit the 2 queries.
    cached = cache_get_json(
        namespace=_USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return DecisionToOutcomeDelayOut(**cached)

    # Decisions per project (ascending) and outcomes per
    # project (ascending). For each decision, find the
    # next outcome on the same project that's strictly
    # after it.
    decision_rows = (
        db.query(
            Decision.id,
            Decision.project_id,
            Decision.created_at,
        )
        .filter(Decision.project_id.in_(owned_project_ids))
        .order_by(Decision.id.asc())
        .all()
    )
    outcome_rows = (
        db.query(
            Outcome.id,
            Outcome.project_id,
            Outcome.created_at,
        )
        .filter(Outcome.project_id.in_(owned_project_ids))
        .order_by(Outcome.id.asc())
        .all()
    )

    # Bucket by project_id.
    decisions_by_pid: dict[int, list] = {}
    for d in decision_rows:
        decisions_by_pid.setdefault(
            d.project_id, []
        ).append(d)
    outcomes_by_pid: dict[int, list] = {}
    for o in outcome_rows:
        outcomes_by_pid.setdefault(
            o.project_id, []
        ).append(o)

    pairs: list[tuple] = []
    for pid in owned_project_ids:
        decs = decisions_by_pid.get(pid, [])
        outs = outcomes_by_pid.get(pid, [])
        for dec in decs:
            # Find the first outcome strictly after dec.
            next_out = next(
                (o for o in outs if o.created_at > dec.created_at),
                None,
            )
            if next_out is not None:
                pairs.append(
                    (dec.created_at, next_out.created_at)
                )

    payload = build_decision_to_outcome_delay(
        decision_outcome_pairs=pairs,
    )
    cache_set_json(
        namespace=_USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_DECISION_TO_OUTCOME_DELAY_CACHE_TTL_S,
    )
    return DecisionToOutcomeDelayOut(**payload)


@router.get(
    "/me/insights",
    response_model=InsightsOut,
    summary=(
        "Per-user executive summary - one-line headline + "
        "2-3 short insight sentences synthesized from "
        "the existing user-level digests"
    ),
    # Read-only; multiple cheap COUNTs in the route.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightsOut:
    """Executive summary.

    Composes a single headline + 2-3 short insight
    sentences synthesized from the existing user-level
    digests. Different from /me/digest-snapshot (which
    is a flat payload of all 5 digests) - this is a
    narrative rollup.
    """
    # Cache hit - short-circuit the 5 COUNTs + the
    # needs-attention loop. Checked BEFORE the DB query
    # below so cache hits don't pay any DB cost.
    cached = cache_get_json(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return InsightsOut(**cached)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]

    project_count = len(owned_project_ids)
    sim_count_total = 0
    decision_count_total = 0
    outcome_count_total = 0
    weekly_sim_count = 0
    weekly_decision_count = 0
    weekly_outcome_count = 0

    if owned_project_ids:
        sim_count_total = (
            db.query(Simulation)
            .filter(Simulation.project_id.in_(owned_project_ids))
            .count()
        )
        decision_count_total = (
            db.query(Decision)
            .filter(Decision.project_id.in_(owned_project_ids))
            .count()
        )
        outcome_count_total = (
            db.query(Outcome)
            .filter(Outcome.project_id.in_(owned_project_ids))
            .count()
        )
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        weekly_sim_count = (
            db.query(Simulation)
            .filter(
                Simulation.project_id.in_(owned_project_ids),
                Simulation.created_at >= seven_days_ago,
            )
            .count()
        )
        weekly_decision_count = (
            db.query(Decision)
            .filter(
                Decision.project_id.in_(owned_project_ids),
                Decision.created_at >= seven_days_ago,
            )
            .count()
        )
        weekly_outcome_count = (
            db.query(Outcome)
            .filter(
                Outcome.project_id.in_(owned_project_ids),
                Outcome.created_at >= seven_days_ago,
            )
            .count()
        )

    # Simple portfolio-score proxy: weighted sum of
    # ratios vs the weekly activity.
    total_recent = max(
        weekly_sim_count + weekly_decision_count +
        weekly_outcome_count,
        1,
    )
    portfolio_score = min(
        100, total_recent * 15 + project_count * 5,
    )
    if portfolio_score >= 70:
        portfolio_verdict = "HEALTHY"
    elif portfolio_score >= 40:
        portfolio_verdict = "NEEDS_ATTENTION"
    else:
        portfolio_verdict = "AT_RISK"

    # Simple needs_attention proxy: projects with
    # pending decision count >= 1 OR outcome count < sim
    # count / 2.
    needs_attention_count = 0
    if owned_project_ids:
        for pid in owned_project_ids:
            pending = (
                db.query(Decision)
                .filter(
                    Decision.project_id == pid,
                    Decision.status.in_(("PENDING", "RUNNING")),
                )
                .count()
            )
            sims = (
                db.query(Simulation)
                .filter(
                    Simulation.project_id == pid,
                    Simulation.status == "COMPLETED",
                )
                .count()
            )
            outcomes = (
                db.query(Outcome)
                .filter(Outcome.project_id == pid)
                .count()
            )
            if pending > 0 or (sims > 0 and outcomes < sims / 2):
                needs_attention_count += 1

    payload = build_insights(
        project_count=project_count,
        sim_count_total=sim_count_total,
        decision_count_total=decision_count_total,
        outcome_count_total=outcome_count_total,
        portfolio_verdict=portfolio_verdict,
        portfolio_score=portfolio_score,
        weekly_sim_count=weekly_sim_count,
        weekly_decision_count=weekly_decision_count,
        weekly_outcome_count=weekly_outcome_count,
        needs_attention_count=needs_attention_count,
    )
    cache_set_json(
        namespace=_USER_INSIGHTS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_INSIGHTS_CACHE_TTL_S,
    )
    return InsightsOut(**payload)


@router.get(
    "/me/last-week-stats",
    response_model=LastWeekStatsOut,
    summary=(
        "Per-user comparative stats - this week (last 7 "
        "days) vs last week (days 8-14 ago) so the dashboard "
        "can show whether activity is accelerating, steady, "
        "or slowing"
    ),
    # Read-only; 6 cheap COUNTs (3 this-week, 3 last-week).
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_last_week_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LastWeekStatsOut:
    """Last-week stats.

    Compares this week (last 7 days) vs last week
    (days 8-14 ago) for sim / decision / outcome counts.
    """
    # Cache hit - short-circuit the 6 COUNTs. Checked
    # BEFORE the DB query below so cache hits skip all DB
    # work (including the empty-project early-return path).
    cached = cache_get_json(
        namespace=_USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return LastWeekStatsOut(**cached)

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return LastWeekStatsOut()

    this_week_start = datetime.now(
        timezone.utc,
    ) - timedelta(days=7)
    last_week_end = this_week_start
    last_week_start = datetime.now(
        timezone.utc,
    ) - timedelta(days=14)

    this_week_counts = {
        "sim_count": 0,
        "decision_count": 0,
        "outcome_count": 0,
    }
    last_week_counts = {
        "sim_count": 0,
        "decision_count": 0,
        "outcome_count": 0,
    }

    this_week_counts["sim_count"] = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.created_at >= this_week_start,
        )
        .count()
    )
    this_week_counts["decision_count"] = (
        db.query(Decision)
        .filter(
            Decision.project_id.in_(owned_project_ids),
            Decision.created_at >= this_week_start,
        )
        .count()
    )
    this_week_counts["outcome_count"] = (
        db.query(Outcome)
        .filter(
            Outcome.project_id.in_(owned_project_ids),
            Outcome.created_at >= this_week_start,
        )
        .count()
    )
    last_week_counts["sim_count"] = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.created_at >= last_week_start,
            Simulation.created_at < last_week_end,
        )
        .count()
    )
    last_week_counts["decision_count"] = (
        db.query(Decision)
        .filter(
            Decision.project_id.in_(owned_project_ids),
            Decision.created_at >= last_week_start,
            Decision.created_at < last_week_end,
        )
        .count()
    )
    last_week_counts["outcome_count"] = (
        db.query(Outcome)
        .filter(
            Outcome.project_id.in_(owned_project_ids),
            Outcome.created_at >= last_week_start,
            Outcome.created_at < last_week_end,
        )
        .count()
    )

    payload = build_last_week_stats(
        this_week_counts=this_week_counts,
        last_week_counts=last_week_counts,
    )
    cache_set_json(
        namespace=_USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_LAST_WEEK_STATS_CACHE_TTL_S,
    )
    return LastWeekStatsOut(**payload)


@router.get(
    "/me/projects-needing-attention",
    response_model=ProjectsNeedingAttentionOut,
    summary=(
        "Per-user projects needing attention - list of "
        "projects whose status-banner would say 'Action "
        "needed' or 'Stale', so the dashboard can surface "
        "a focused 'what to look at next' widget"
    ),
    # Read-only; per-project loops.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_projects_needing_attention(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectsNeedingAttentionOut:
    """Projects needing attention.

    Lists owned projects whose status-banner verdict
    would be 'Stale' or 'Action needed', so the dashboard
    can surface a focused 'what to look at next' widget.
    """
    from app.simulation.status_banner import build_status_banner

    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return ProjectsNeedingAttentionOut(
            narrative="No projects on file yet.",
        )

    # Cache hit - short-circuit the per-project loop.
    cached = cache_get_json(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectsNeedingAttentionOut(**cached)
        )

    # Per-project sim + outcome + decision counts so the
    # helper can decide which reason applies.
    project_rows = []
    for pid in owned_project_ids:
        project = (
            db.query(Project)
            .filter(Project.id == pid)
            .first()
        )
        if project is None:
            continue

        latest_sim = (
            db.query(Simulation)
            .filter(
                Simulation.project_id == pid,
                Simulation.status == "COMPLETED",
            )
            .order_by(Simulation.created_at.desc())
            .first()
        )
        sim_count = (
            db.query(Simulation)
            .filter(
                Simulation.project_id == pid,
                Simulation.status == "COMPLETED",
            )
            .count()
        )
        outcome_count = (
            db.query(Outcome)
            .filter(Outcome.project_id == pid)
            .count()
        )
        pending_decision_count = (
            db.query(Decision)
            .filter(
                Decision.project_id == pid,
                Decision.status.in_(("PENDING", "RUNNING")),
            )
            .count()
        )

        # Compute the days_since_latest_assumption for
        # the status-banner helper.
        assumption_count = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == pid,
                Assumption.is_hidden.is_(False),
            )
            .count()
        )
        days_since_latest_assumption = None
        if assumption_count > 0:
            latest_assumption = (
                db.query(Assumption)
                .filter(
                    Assumption.project_id == pid,
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

        sim_confidence = None
        if latest_sim is not None:
            sim_confidence = getattr(
                latest_sim, "confidence_score", None,
            )
            if sim_confidence is not None:
                sim_confidence = float(sim_confidence) / 100.0
        has_completed_sim = latest_sim is not None
        has_outcome = outcome_count > 0

        weak_link_count = 0
        if assumption_count > 0:
            from app.simulation.assumption_digest import (
                build_assumption_digest,
            )
            assumption_rows = (
                db.query(Assumption)
                .filter(
                    Assumption.project_id == pid,
                    Assumption.is_hidden.is_(False),
                )
                .all()
            )
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

        banner_payload = build_status_banner(
            brief_completed=getattr(
                project, "brief_completed_at", None,
            ) is not None,
            assumption_count=assumption_count,
            has_completed_sim=has_completed_sim,
            days_since_latest_sim=(
                _days_since(getattr(
                    latest_sim, "created_at", None,
                ))
            ),
            pending_decision_count=pending_decision_count,
            days_since_latest_assumption=(
                days_since_latest_assumption
            ),
        )
        project_rows.append({
            "project_id": pid,
            "project_title": getattr(project, "title", None),
            "status": banner_payload["status"],
            "sims_count": sim_count,
            "outcomes_count": outcome_count,
        })

    payload = build_projects_needing_attention(
        project_status_rows=project_rows,
    )
    cache_set_json(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_TTL_S,
    )
    return ProjectsNeedingAttentionOut(**payload)


def _days_since(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - ts).days)


@router.get(
    "/me/sim-failure-rate",
    response_model=SimFailureRateOut,
    summary=(
        "Per-user sim failure rate - what % of sims ended "
        "in FAILED status so the dashboard can show a "
        "system-reliability widget"
    ),
    # Read-only; 2 cheap COUNTs.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_sim_failure_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimFailureRateOut:
    """Sim failure rate.

    Computes the % of completed sims (any status) that
    ended in FAILED across the user's projects.
    """
    owned_project_ids = [
        pid for (pid,) in
        db.query(Project.id)
        .filter(Project.user_id == current_user.id)
        .all()
    ]
    if not owned_project_ids:
        return SimFailureRateOut(
            narrative="No projects on file yet.",
        )

    # Cache hit - short-circuit the 2 COUNTs.
    cached = cache_get_json(
        namespace=_USER_SIM_FAILURE_RATE_CACHE_NAMESPACE,
        params={"user_id": current_user.id},
        user_id=current_user.id,
    )
    if cached is not None:
        return SimFailureRateOut(**cached)

    total_simulations = (
        db.query(Simulation)
        .filter(Simulation.project_id.in_(owned_project_ids))
        .count()
    )
    failed_simulations = (
        db.query(Simulation)
        .filter(
            Simulation.project_id.in_(owned_project_ids),
            Simulation.status == "FAILED",
        )
        .count()
    )

    payload = build_sim_failure_rate(
        total_simulations=total_simulations,
        failed_simulations=failed_simulations,
    )
    return SimFailureRateOut(**payload)
