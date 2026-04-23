from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.auth import MessageResponse

router = APIRouter(prefix="/users", tags=["users"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


@router.post(
    "/me/clear-archive",
    response_model=MessageResponse,
    summary="Delete all projects owned by the current user",
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
