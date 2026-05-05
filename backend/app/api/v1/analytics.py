from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _require_admin(current_user: User) -> None:
    if getattr(current_user, "is_admin", False):
        return
    if settings.ADMIN_EMAILS:
        allowed = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
        if current_user.email and current_user.email.lower() in allowed:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.get(
    "/platform",
    summary="Admin platform analytics aggregates",
    responses=_JSON_200,
)
def platform_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_admin(current_user)

    product_types = db.execute(
        text("""
        SELECT results_json->>'product_type_detected' AS pt,
               COUNT(*)::int AS count
        FROM simulations WHERE UPPER(status) = 'COMPLETED'
          AND results_json->>'product_type_detected' IS NOT NULL
        GROUP BY pt ORDER BY count DESC
    """)
    ).mappings().all()

    architects = db.execute(
        text("""
        SELECT results_json->>'primary_failure_domain' AS arch,
               COUNT(*)::int AS count
        FROM simulations WHERE UPPER(status) = 'COMPLETED'
          AND results_json->>'primary_failure_domain' IS NOT NULL
        GROUP BY arch ORDER BY count DESC LIMIT 10
    """)
    ).mappings().all()

    signal_quality = db.execute(
        text("""
        SELECT
          COUNT(*) FILTER (WHERE signal_quality >= 0.5)::int  AS full_signal,
          COUNT(*) FILTER (WHERE signal_quality >= 0.25
                           AND signal_quality < 0.5)::int     AS partial_signal,
          COUNT(*) FILTER (WHERE signal_quality < 0.25 OR signal_quality IS NULL)::int  AS low_signal
        FROM simulations WHERE UPPER(status) = 'COMPLETED'
    """)
    ).mappings().first()

    intake_dist = db.execute(
        text("""
        SELECT COALESCE(intake_mode, 'IDEA') AS intake_mode, COUNT(*)::int AS count
        FROM projects GROUP BY COALESCE(intake_mode, 'IDEA')
    """)
    ).mappings().all()

    outcome_gap = db.execute(
        text("""
        SELECT
          COUNT(DISTINCT s.id)::int AS total_completed,
          COUNT(DISTINCT fo.simulation_id)::int AS have_outcome
        FROM simulations s
        LEFT JOIN founder_outcomes fo ON fo.simulation_id = s.id
        WHERE UPPER(s.status) = 'COMPLETED'
    """)
    ).mappings().first()

    tc = int(outcome_gap["total_completed"] or 0) if outcome_gap else 0
    ho = int(outcome_gap["have_outcome"] or 0) if outcome_gap else 0
    gap_pct = round((1 - ho / max(tc, 1)) * 100, 1) if outcome_gap else 0.0

    return {
        "product_types": [
            {"type": r["pt"], "count": r["count"]} for r in product_types if r.get("pt")
        ],
        "primary_failure_domains": [
            {"architect": r["arch"], "count": r["count"]} for r in architects if r.get("arch")
        ],
        "signal_quality": {
            "full": int(signal_quality["full_signal"] or 0) if signal_quality else 0,
            "partial": int(signal_quality["partial_signal"] or 0) if signal_quality else 0,
            "low": int(signal_quality["low_signal"] or 0) if signal_quality else 0,
        },
        "intake_mode_distribution": [
            {"mode": r["intake_mode"] or "IDEA", "count": r["count"]} for r in intake_dist
        ],
        "outcome_return_rate": {
            "total_completed": tc,
            "have_outcome": ho,
            "gap_pct": gap_pct,
        },
    }


@router.post(
    "/founder-outcome",
    summary="Record founder outcome for a simulation",
    responses=_JSON_200,
)
def submit_founder_outcome(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sim_id = body.get("simulation_id")
    if not sim_id:
        raise HTTPException(status_code=400, detail="simulation_id required")

    row = db.execute(
        text("""
        SELECT s.id, s.project_id, s.signal_quality
        FROM simulations s
        JOIN projects p ON p.id = s.project_id
        WHERE s.id = :sid AND p.user_id = :uid
    """),
        {"sid": int(sim_id), "uid": current_user.id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")

    project_id = int(row.project_id)
    sq = float(row.signal_quality or 0.0)
    launched = bool(body.get("launched", False))
    acr_raw = body.get("actual_conversion_rate")
    acr: float | None
    if acr_raw is None or acr_raw == "":
        acr = 0.0 if not launched else 0.0
    else:
        try:
            acr = float(acr_raw)
        except (TypeError, ValueError):
            acr = 0.0
    notes = str(body.get("notes", ""))[:500]

    existing = db.execute(
        text("SELECT id FROM founder_outcomes WHERE simulation_id = :sid"),
        {"sid": int(sim_id)},
    ).fetchone()

    if existing:
        db.execute(
            text("""
            UPDATE founder_outcomes
            SET launched = :launched,
                actual_conversion_rate = :acr,
                notes = :notes,
                user_id = COALESCE(user_id, :uid)
            WHERE simulation_id = :sid
        """),
            {
                "launched": launched,
                "acr": acr,
                "notes": notes,
                "uid": current_user.id,
                "sid": int(sim_id),
            },
        )
    else:
        db.execute(
            text("""
            INSERT INTO founder_outcomes
            (simulation_id, user_id, project_id, days_since_launch, actual_conversion_rate,
             launched, notes, data_confidence, product_changed_since_sim, pricing_changed,
             target_market_changed, signal_quality_at_run, learning_weight, validated, created_at)
            VALUES
            (:sid, :uid, :pid, 30, :acr, :launched, :notes, 'ESTIMATED', false, false, false,
             :sq, 0.0, false, NOW())
        """),
            {
                "sid": int(sim_id),
                "uid": current_user.id,
                "pid": project_id,
                "acr": acr,
                "launched": launched,
                "notes": notes,
                "sq": sq,
            },
        )
    db.commit()
    return {"status": "outcome_recorded"}


@router.get(
    "/check-outcome-gate/{project_id}",
    summary="Check whether outcome gate applies for a project",
    responses=_JSON_200,
)
def check_outcome_gate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    own = db.execute(
        text("SELECT id FROM projects WHERE id = :pid AND user_id = :uid"),
        {"pid": project_id, "uid": current_user.id},
    ).fetchone()
    if not own:
        raise HTTPException(status_code=404, detail="Project not found")

    all_projects = db.execute(
        text("""
        SELECT id FROM projects
        WHERE user_id = :uid ORDER BY created_at ASC
    """),
        {"uid": current_user.id},
    ).fetchall()

    project_ids = [int(r.id) for r in all_projects]
    if len(project_ids) < 2:
        return {"gate_active": False}

    current_idx = next((i for i, pid in enumerate(project_ids) if pid == project_id), -1)
    if current_idx <= 0:
        return {"gate_active": False}

    prev_project_id = project_ids[current_idx - 1]

    prev_sim = db.execute(
        text("""
        SELECT s.id FROM simulations s
        LEFT JOIN founder_outcomes fo ON fo.simulation_id = s.id
        WHERE s.project_id = :pid AND UPPER(s.status) = 'COMPLETED'
          AND fo.id IS NULL
        ORDER BY s.created_at DESC
        LIMIT 1
    """),
        {"pid": prev_project_id},
    ).fetchone()

    if not prev_sim:
        return {"gate_active": False}

    return {
        "gate_active": True,
        "prev_project_id": prev_project_id,
        "prev_sim_id": int(prev_sim.id),
        "message": "Unlock full report by sharing how your last product performed",
    }
