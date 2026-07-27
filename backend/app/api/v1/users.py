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
from app.models.decision import Decision
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.user import AccountHealthOut, UserDashboardOut
from app.simulation.account_health import build_account_health
from app.simulation.calibration_health import (
    build_calibration_health,
)
from app.simulation.user_dashboard import (
    build_user_dashboard,
)

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
