from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.rate_limiter import rate_limit
from app.models.user import User
from app.schemas.calibration import (
    ArchitectWeightedDrift,
    CalibrationStatusOut,
    WeightedDriftSummary,
)
from app.schemas.outcome import FounderOutcomeSubmit
from app.schemas.portfolio import UserPortfolioOut
from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
from app.simulation.calibration_insights import (
    build_architect_health,
    build_outcome_coverage,
    build_product_type_breakdown,
    build_weighted_drift,
    summarise_calibration,
)
from app.simulation.founder_outcomes_export import (
    founder_outcomes_to_csv,
    predicted_conversion_from_results,
)
from app.simulation.portfolio_analytics import (
    build_conversion_distribution,
    build_failure_domain_counts,
    build_recent_projects,
    build_status_breakdown,
    build_stress_test_coverage,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _require_admin(current_user: User) -> None:
    """Deprecated alias — see :func:`app.core.deps.require_admin`."""
    require_admin(current_user)


@router.get(
    "/platform",
    summary="Admin platform analytics aggregates",
    responses=_JSON_200,
    # Defense-in-depth: even an authenticated admin shouldn't
    # be able to spam 5-6 full-table GROUP BYs. 10/min/IP
    # keeps accidental dashboard-script loops bounded without
    # blocking normal admin polling.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
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
    # DB write — cap path-spam at 30/min/IP for the same reason as
    # the simulations POST limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def submit_founder_outcome(
    body: FounderOutcomeSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sim_id = body.simulation_id

    row = db.execute(
        text("""
        SELECT s.id, s.project_id, s.signal_quality
        FROM simulations s
        JOIN projects p ON p.id = s.project_id
        WHERE s.id = :sid AND p.user_id = :uid
    """),
        {"sid": sim_id, "uid": current_user.id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")

    project_id = int(row.project_id)
    sq = float(row.signal_quality or 0.0)
    launched = body.launched
    acr = body.actual_conversion_rate
    notes = body.notes or ""

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
    "/founder-outcomes/export",
    summary="Export all founder outcomes as CSV (or JSON)",
    response_class=StreamingResponse,
    # Admin-only audit export of the learning layer. 10/min/IP keeps a
    # stray admin token from driving repeated full-table scans.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def export_founder_outcomes(
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "enriched rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of the calibration learning layer."""
    _require_admin(current_user)

    rows_raw = db.execute(
        text("""
            SELECT
                fo.id,
                fo.simulation_id,
                fo.project_id,
                p.title AS project_title,
                fo.created_at,
                fo.launched,
                fo.actual_conversion_rate,
                fo.days_since_launch,
                fo.data_confidence,
                fo.product_changed_since_sim,
                fo.pricing_changed,
                fo.target_market_changed,
                fo.signal_quality_at_run,
                fo.validated,
                fo.learning_weight,
                fo.notes,
                s.results_json
            FROM founder_outcomes fo
            JOIN simulations s ON s.id = fo.simulation_id
            JOIN projects p ON p.id = fo.project_id
            ORDER BY fo.created_at DESC, fo.id DESC
        """)
    ).mappings().all()

    rows = []
    for raw in rows_raw:
        predicted = predicted_conversion_from_results(raw.get("results_json"))
        rows.append(
            {
                "id": raw.get("id"),
                "simulation_id": raw.get("simulation_id"),
                "project_id": raw.get("project_id"),
                "project_title": raw.get("project_title"),
                "created_at": raw.get("created_at"),
                "launched": raw.get("launched"),
                "actual_conversion_rate": raw.get("actual_conversion_rate"),
                "predicted_conversion_rate": predicted,
                "signal_quality_at_run": raw.get("signal_quality_at_run"),
                "days_since_launch": raw.get("days_since_launch"),
                "data_confidence": raw.get("data_confidence"),
                "product_changed_since_sim": raw.get("product_changed_since_sim"),
                "pricing_changed": raw.get("pricing_changed"),
                "target_market_changed": raw.get("target_market_changed"),
                "validated": raw.get("validated"),
                "learning_weight": raw.get("learning_weight"),
                "notes": raw.get("notes"),
            }
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        payload = {
            "generated_at": generated_at,
            "user_id": current_user.id,
            "total": len(rows),
            "rows": rows,
        }
        body = json.dumps(payload, default=str, indent=2).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="founder-outcomes.json"',
                "Content-Length": str(len(body)),
            },
        )

    csv_text = founder_outcomes_to_csv(
        rows,
        metadata={"generated_at": generated_at, "user_id": current_user.id},
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="founder-outcomes.csv"',
            "Content-Length": str(len(body)),
        },
    )


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


@router.get(
    "/me/portfolio",
    response_model=UserPortfolioOut,
    summary="Authenticated user's portfolio rollup (no admin gate)",
    responses=_JSON_200,
)
def my_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserPortfolioOut:
    """
    Returns a single dashboard view across the authenticated user's projects:
    counts by status, latest-completed conversion rate distribution, primary
    failure domain frequency, stress-test coverage, and recent activity.

    Scoped strictly to ``current_user.id`` — does not require admin.
    """
    user_id = int(current_user.id)

    # 1. Project counts by status (excludes archived by default — they're
    # still counted in the total but separated so the UI can filter).
    project_rows = db.execute(
        text("""
        SELECT status, COUNT(*)::int AS count FROM projects
        WHERE user_id = :uid
        GROUP BY status
    """),
        {"uid": user_id},
    ).mappings().all()

    # 2. Simulation counts by status (across the user's projects).
    sim_rows = db.execute(
        text("""
        SELECT s.status, COUNT(*)::int AS count
        FROM simulations s
        JOIN projects p ON p.id = s.project_id
        WHERE p.user_id = :uid
        GROUP BY s.status
    """),
        {"uid": user_id},
    ).mappings().all()

    # 3. Latest completed simulation per project → conversion_rate.
    latest_per_project = db.execute(
        text("""
        WITH latest AS (
            SELECT DISTINCT ON (s.project_id)
                s.project_id,
                s.results_json->>'overall_conversion_rate' AS conversion_rate
            FROM simulations s
            JOIN projects p ON p.id = s.project_id
            WHERE p.user_id = :uid
              AND UPPER(s.status) = 'COMPLETED'
              AND s.results_json IS NOT NULL
              AND s.results_json ? 'overall_conversion_rate'
            ORDER BY s.project_id, s.created_at DESC
        )
        SELECT conversion_rate FROM latest
    """),
        {"uid": user_id},
    ).mappings().all()

    # 4. Primary failure domain distribution.
    failure_rows = db.execute(
        text("""
        SELECT results_json->>'primary_failure_domain' AS architect,
               COUNT(*)::int AS count
        FROM simulations s
        JOIN projects p ON p.id = s.project_id
        WHERE p.user_id = :uid
          AND UPPER(s.status) = 'COMPLETED'
          AND results_json->>'primary_failure_domain' IS NOT NULL
        GROUP BY architect
        ORDER BY count DESC LIMIT 10
    """),
        {"uid": user_id},
    ).mappings().all()

    # 5. Stress-test coverage — pull the JSONB so the helper can inspect it.
    stress_rows = db.execute(
        text("""
        SELECT stress_test_json FROM projects
        WHERE user_id = :uid
    """),
        {"uid": user_id},
    ).mappings().all()

    # 6. Outcome coverage.
    outcome_total = db.execute(
        text("""
        SELECT COUNT(*)::int AS total FROM simulations s
        JOIN projects p ON p.id = s.project_id
        WHERE p.user_id = :uid AND UPPER(s.status) = 'COMPLETED'
    """),
        {"uid": user_id},
    ).scalar_one()
    outcome_with = db.execute(
        text("""
        SELECT COUNT(DISTINCT fo.simulation_id)::int AS with_outcome
        FROM founder_outcomes fo
        JOIN simulations s ON s.id = fo.simulation_id
        JOIN projects p ON p.id = s.project_id
        WHERE p.user_id = :uid
    """),
        {"uid": user_id},
    ).scalar_one()

    # 7. Recent projects (latest 5 by updated_at) with their latest sim.
    recent_rows = db.execute(
        text("""
        SELECT
            p.id, p.title, p.status, p.updated_at,
            (s.status = 'COMPLETED') AS has_completed_simulation,
            s.results_json->>'overall_conversion_rate' AS latest_conversion_rate,
            s.results_json->>'primary_failure_domain' AS primary_failure_domain
        FROM projects p
        LEFT JOIN LATERAL (
            SELECT status, results_json, created_at
            FROM simulations
            WHERE project_id = p.id AND UPPER(status) = 'COMPLETED'
            ORDER BY created_at DESC LIMIT 1
        ) s ON true
        WHERE p.user_id = :uid
        ORDER BY p.updated_at DESC
        LIMIT 5
    """),
        {"uid": user_id},
    ).mappings().all()

    return UserPortfolioOut(
        user_id=user_id,
        projects=build_status_breakdown([dict(r) for r in project_rows]),
        simulations=build_status_breakdown([dict(r) for r in sim_rows]),
        conversion_distribution=build_conversion_distribution(
            [dict(r) for r in latest_per_project]
        ),
        primary_failure_domains=build_failure_domain_counts(
            [dict(r) for r in failure_rows]
        ),
        stress_test_coverage=build_stress_test_coverage(
            [dict(r) for r in stress_rows]
        ),
        outcome_coverage={
            "simulations_total": int(outcome_total or 0),
            "with_outcome": int(outcome_with or 0),
        },
        recent_projects=build_recent_projects([dict(r) for r in recent_rows]),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/calibration/status",
    response_model=CalibrationStatusOut,
    summary="Calibration engine state (admin only)",
    responses=_JSON_200,
)
def calibration_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalibrationStatusOut:
    """
    Returns the current calibration state across the 5-layer engine:
    founder-outcome coverage, per-architect correction factors,
    confidence/samples, and a list of architects that still need more data.

    Admin-only — calibration is a global signal shared across all users.
    """
    _require_admin(current_user)

    outcome_total = int(
        db.execute(text("SELECT COUNT(*)::int FROM founder_outcomes")).scalar_one() or 0
    )
    outcome_validated = int(
        db.execute(
            text(
                "SELECT COUNT(*)::int FROM founder_outcomes WHERE validated=true AND learning_weight > 0"
            )
        ).scalar_one()
        or 0
    )
    outcome_rejected = int(
        db.execute(
            text(
                "SELECT COUNT(*)::int FROM founder_outcomes WHERE validated=false AND learning_weight = 0"
            )
        ).scalar_one()
        or 0
    )

    correction_rows = db.execute(
        text("""
        SELECT architect_name, product_type, product_attribute, cluster_id,
               correction_scalar, confidence_weight, effective_sample_count,
               scope, last_updated
        FROM architect_corrections
        ORDER BY architect_name, product_type, cluster_id
    """)
    ).mappings().all()

    corrections_list = [dict(r) for r in correction_rows]
    by_architect = build_architect_health(corrections_list, list(ALL_ARCHITECT_NAMES))
    summary = summarise_calibration(by_architect, corrections_list)
    product_breakdown = build_product_type_breakdown(corrections_list)
    drift_payload = build_weighted_drift(
        corrections_list, list(ALL_ARCHITECT_NAMES)
    )
    drift_summary = WeightedDriftSummary(
        total_architects=drift_payload["total_architects"],
        biased_up_count=drift_payload["biased_up_count"],
        biased_down_count=drift_payload["biased_down_count"],
        stable_count=drift_payload["stable_count"],
        by_architect=[
            ArchitectWeightedDrift(**row) for row in drift_payload["by_architect"]
        ],
    )

    return CalibrationStatusOut(
        outcome_coverage=build_outcome_coverage(
            outcome_total, outcome_validated, outcome_rejected
        ),
        total_correction_rows=summary["total_correction_rows"],
        by_architect=by_architect,
        by_product_type=product_breakdown,
        calibrated_architects=summary["calibrated_architects"],
        under_calibrated_architects=summary["under_calibrated_architects"],
        under_calibrated_list=summary["under_calibrated_list"],
        weighted_drift=drift_summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
