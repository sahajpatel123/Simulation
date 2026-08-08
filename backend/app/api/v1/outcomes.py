from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.v1.cache_namespaces import _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE
from app.api.v1.common import get_owned_project
from app.api.v1.projects import (
    _ACTIVITY_FEED_CACHE_NAMESPACE,
    _LATEST_SNAPSHOT_CACHE_NAMESPACE,
    _NEXT_ACTION_CACHE_NAMESPACE,
    _PROJECT_HEALTH_CACHE_NAMESPACE,
    _STALE_CHECK_CACHE_NAMESPACE,
)
from app.api.v1.users import (
    _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
    _USER_DASHBOARD_CACHE_NAMESPACE,
    _USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE,
    _USER_INSIGHTS_CACHE_NAMESPACE,
    _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
    _USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
    _USER_OLDEST_OPEN_ITEM_CACHE_NAMESPACE,
    _USER_OUTCOME_RATE_CACHE_NAMESPACE,
    _USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
    _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
    _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
    _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
    _USER_QUICK_STATS_CACHE_NAMESPACE,
    _USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
    _USER_RUNS_PER_WEEK_CACHE_NAMESPACE,
    _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
    _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
)
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
from app.models.outcome import Outcome
from app.models.outcome_tracker import OutcomeTracker
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.funnel_calibration import FunnelCalibrationDigestOut
from app.schemas.outcome import (
    OutcomeCreate,
    OutcomeDigestOut,
    OutcomeFeedbackRequest,
    OutcomeHistoryOut,
    OutcomeRecord,
    VarianceReport,
)
from app.schemas.outcome_benchmark import OutcomeBenchmarkOut
from app.schemas.outcome_tracker import (
    OutcomeTrackerCreate,
    OutcomeTrackerPoint,
    OutcomeTrackerTimelineOut,
)
from app.simulation.architect_accuracy_bridge import (
    bridge_architect_accuracy,
)
from app.simulation.architect_leaderboard import (
    build_architect_leaderboard,
)
from app.simulation.calibration_health import (
    build_calibration_health,
)
from app.simulation.founder_outcomes_export import (
    predicted_conversion_from_results,
)
from app.simulation.funnel_calibration import (
    build_funnel_calibration_digest,
)
from app.simulation.outcome_benchmark import (
    MAX_PEERS,
    build_outcome_benchmark,
)
from app.simulation.outcome_tracker_export import (
    outcome_tracker_to_csv,
)
from app.simulation.outcome_tracker_read import (
    build_outcome_tracker_timeline,
)
from app.simulation.outcomes_digest_v2 import (
    build_outcomes_digest,
)
from app.simulation.outcomes_export import outcomes_to_csv

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["outcomes"])


def _json_default(value: Any) -> str:
    """Serialize non-JSON values for export payloads deterministically.

    Datetimes are rendered as ISO 8601 strings (matching the CSV export and
    the timeline endpoint) instead of Python's space-separated ``str()``.
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# Outcomes digest cache — single source of truth so
# future rename propagates to every invalidation site.
# 120s TTL matches the digest's internal cache.
_OUTCOMES_DIGEST_CACHE_NAMESPACE: str = "project-outcomes-digest"
_FUNNEL_CALIBRATION_CACHE_NAMESPACE: str = "project-funnel-calibration"

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

PENALTY_RATES = {
    "conversion": 1.8,
    "mrr": 1.2,
    "cac": 1.0,
    "churn": 1.4,
}
METRIC_WEIGHTS = {
    "conversion": 0.40,
    "mrr": 0.25,
    "cac": 0.20,
    "churn": 0.15,
}


def _variance_pct(actual: float, predicted: float | None) -> float | None:
    if predicted is None or predicted == 0.0:
        return None
    return round((actual - predicted) / abs(predicted) * 100.0, 2)


def _metric_score(actual: float, predicted: float | None, penalty: float) -> float | None:
    if predicted is None or predicted == 0.0:
        return None
    error_pct = abs((actual - predicted) / abs(predicted)) * 100.0
    return max(0.0, round(100.0 - error_pct * penalty, 2))


def _calibration_score(
    actual_conv: float,
    actual_mrr: float,
    actual_cac: float,
    actual_churn: float,
    pred_conv: float | None,
    pred_mrr: float | None,
) -> float:
    scores: dict[str, float] = {}

    s_conv = _metric_score(actual_conv, pred_conv, PENALTY_RATES["conversion"])
    if s_conv is not None:
        scores["conversion"] = s_conv

    s_mrr = _metric_score(actual_mrr, pred_mrr, PENALTY_RATES["mrr"])
    if s_mrr is not None:
        scores["mrr"] = s_mrr

    # MVP currently has no predicted CAC/churn fields in simulation output.
    _ = actual_cac, actual_churn

    if not scores:
        if 0.01 <= actual_conv <= 0.15:
            return 50.0
        return 30.0

    total_weight = sum(METRIC_WEIGHTS[key] for key in scores)
    weighted_sum = sum(scores[key] * METRIC_WEIGHTS[key] for key in scores)
    return round(weighted_sum / total_weight, 2)


def _calibration_trend(outcomes: list[Outcome]) -> str:
    if len(outcomes) < 3:
        return "INSUFFICIENT_DATA"

    scores = [o.calibration_score for o in outcomes[:3] if o.calibration_score is not None]
    if len(scores) < 3:
        return "INSUFFICIENT_DATA"

    delta_recent = scores[0] - scores[1]
    delta_older = scores[1] - scores[2]

    if delta_recent > 5 and delta_older > 0:
        return "IMPROVING"
    if delta_recent < -5 and delta_older < 0:
        return "DEGRADING"
    return "STABLE"


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a query datetime to UTC so DB comparisons are stable.

    Naive datetimes are treated as UTC (the API documents both
    ``start_date`` and ``end_date`` as UTC). Aware datetimes are
    converted to UTC instead of being passed through in whatever
    offset the caller happened to use.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hydrate_record(outcome: Outcome) -> OutcomeRecord:
    return OutcomeRecord(
        id=outcome.id,
        project_id=outcome.project_id,
        actual_conversion_rate=outcome.actual_conversion_rate,
        actual_mrr=outcome.actual_mrr,
        actual_cac=outcome.actual_cac,
        actual_churn_rate=outcome.actual_churn_rate,
        days_since_launch=outcome.days_since_launch,
        actual_dau=outcome.actual_dau,
        actual_nps=outcome.actual_nps,
        notes=outcome.notes,
        predicted_conversion_rate=outcome.predicted_conversion_rate,
        predicted_mrr=outcome.predicted_mrr,
        simulation_id=outcome.simulation_id,
        variance=VarianceReport(
            conversion=outcome.variance_conversion,
            mrr=outcome.variance_mrr,
            cac=outcome.variance_cac,
            churn=outcome.variance_churn,
        ),
        calibration_score=outcome.calibration_score or 0.0,
        recorded_at=outcome.created_at,
    )


def _predicted_from_results(results: dict) -> float:
    return float(
        results.get("mean_conversion_rate")
        or results.get("conversion_rate")
        or results.get("population_weighted_conversion")
        or 0
    )


def _predicted_revenue_from_results(results: dict) -> float | None:
    """Best-effort predicted revenue from a completed results payload."""
    for key in (
        "mean_revenue",
        "revenue_projection",
        "projected_revenue",
        "annual_revenue_projection",
    ):
        raw = results.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _hydrate_tracker_point(row: OutcomeTracker) -> OutcomeTrackerPoint:
    return OutcomeTrackerPoint(
        id=row.id,
        project_id=row.project_id,
        simulation_id=row.simulation_id,
        recorded_at=row.recorded_at,
        actual_conversion_rate=row.actual_conversion_rate,
        actual_revenue=row.actual_revenue,
        predicted_conversion_rate=row.predicted_conversion_rate,
        predicted_revenue=row.predicted_revenue,
        variance=row.variance,
        notes=row.notes,
    )


@router.post(
    "/{project_id}/outcome-feedback",
    summary="Submit founder outcome with calibration pipeline (full flow)",
    responses=_JSON_200,
    # Outcome submission kicks off CalibrationEngine + a
    # potential Celery task. Cap path-spam at 10/min/IP so
    # a runaway script can't trigger many concurrent
    # calibration runs against the same project.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def submit_outcome_feedback(
    project_id: int,
    body: OutcomeFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit real-world launch outcomes to improve future simulation accuracy.
    Runs CalibrationEngine Layer 1 + 4 synchronously; schedules Layer 2 via
    Celery if new effective_sample_count crosses the activation threshold (10).
    """
    from app.simulation.calibration_engine import CalibrationEngine
    from app.tasks.calibration_tasks import run_systematic_bias_update

    simulation_id = body.simulation_id
    actual_cr = body.actual_conversion_rate

    get_owned_project(db, current_user.id, project_id)

    sim = (
        db.query(Simulation)
        .filter(Simulation.id == simulation_id, Simulation.project_id == project_id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")

    results = sim.results_json or {}
    predicted = _predicted_from_results(results)

    # ── Plausibility guard ──
    if predicted > 0.10:
        if actual_cr > predicted * 3.0:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This outcome falls outside the plausible range. "
                    "actual_conversion_rate is more than 3× predicted. "
                    "Please verify your numbers or contact support."
                ),
            )
        if actual_cr < predicted * 0.10:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This outcome falls outside the plausible range. "
                    "actual_conversion_rate is less than 10% of predicted. "
                    "Please verify your numbers or contact support."
                ),
            )

    # ── Compute learning_weight ──
    conf_weights = {"EXACT": 1.0, "ESTIMATED": 0.6, "ROUGH": 0.3}
    data_confidence = body.data_confidence
    product_changed = body.product_changed_since_sim
    conf_w = conf_weights.get(data_confidence, 0.3)
    sq = float(sim.signal_quality or 0.0)

    if product_changed:
        learning_weight = 0.0
    elif sq >= 0.50:
        learning_weight = sq * conf_w
    elif sq >= 0.25:
        learning_weight = sq * 0.5 * conf_w
    else:
        learning_weight = 0.0

    # ── Persist to founder_outcomes ──
    db.execute(
        text("""
            INSERT INTO founder_outcomes
            (simulation_id, project_id, days_since_launch, actual_conversion_rate,
             actual_drop_at_browse_pct, actual_drop_at_consider_pct, actual_drop_at_decide_pct,
             primary_failure_reason, product_changed_since_sim, pricing_changed,
             target_market_changed, data_confidence, signal_quality_at_run,
             learning_weight, validated, created_at)
            VALUES (:sid, :pid, :days, :acr, :br, :cr_val, :dr,
                    :pfr, :pc, :pricing, :tm, :dc, :sq, :lw, :val, NOW())
        """),
        {
            "sid": simulation_id,
            "pid": project_id,
            "days": body.days_since_launch,
            "acr": actual_cr,
            "br": body.actual_drop_at_browse_pct,
            "cr_val": body.actual_drop_at_consider_pct,
            "dr": body.actual_drop_at_decide_pct,
            "pfr": body.primary_failure_reason,
            "pc": product_changed,
            "pricing": body.pricing_changed,
            "tm": body.target_market_changed,
            "dc": data_confidence,
            "sq": sq,
            "lw": learning_weight,
            "val": learning_weight > 0.0,
        },
    )
    db.commit()

    outcome_row = db.execute(
        text(
            "SELECT * FROM founder_outcomes "
            "WHERE simulation_id=:sid ORDER BY id DESC LIMIT 1"
        ),
        {"sid": simulation_id},
    ).fetchone()

    if not outcome_row:
        raise HTTPException(status_code=500, detail="Failed to load inserted outcome row")

    class _OutcomeProxy:
        def __init__(self, r, lw: float) -> None:
            self.id = r.id
            self.actual_conversion_rate = float(r.actual_conversion_rate)
            self.product_changed_since_sim = bool(r.product_changed_since_sim)
            self.data_confidence = r.data_confidence
            self.learning_weight = lw
            self.validated = lw > 0.0

    outcome = _OutcomeProxy(outcome_row, learning_weight)

    # ── Layer 4: user accuracy profile (synchronous, fast) ──
    eng = CalibrationEngine()
    will_learn = eng.validate_outcome(outcome, sim, db)
    eng.update_user_accuracy_profile(current_user.id, outcome, sim, db)

    # ── Check whether Layer 2 threshold is newly crossed → fire Celery task ──
    product_type_detected = results.get("product_type_detected") or "saas"
    try:
        eff_count_row = db.execute(
            text("""
                SELECT COALESCE(SUM(learning_weight), 0) AS eff
                FROM founder_outcomes fo
                JOIN simulations s ON s.id = fo.simulation_id
                WHERE fo.validated = true
                  AND fo.learning_weight > 0
                  AND s.results_json->>'product_type_detected' = :pt
            """),
            {"pt": product_type_detected},
        ).fetchone()
        eff_count = float(eff_count_row.eff) if eff_count_row else 0.0
        if eff_count >= 10:
            run_systematic_bias_update.delay()
            logger.info(
                "[OutcomeFeedback] Triggered systematic bias update for product_type=%s (eff=%.1f)",
                product_type_detected,
                eff_count,
            )
    except Exception as exc:
        logger.warning("[OutcomeFeedback] Could not trigger bias update: %s", exc)

    # ── Latest accuracy trend ──
    trend_row = db.execute(
        text("""
            SELECT accuracy_trend
            FROM user_simulation_accuracy_history
            WHERE user_id=:uid ORDER BY created_at DESC LIMIT 1
        """),
        {"uid": current_user.id},
    ).fetchone()
    trend = trend_row.accuracy_trend if trend_row else "INSUFFICIENT_DATA"

    # Bust the cached per-project next-action + the
    # activity feed so the dashboard reflects the new
    # outcome immediately (the calibration verdict is
    # exactly what drives priority-3 of the next-action
    # priority chain; the outcome_submitted event also
    # belongs on the timeline; the new outcome is also
    # a direct input to the outcomes-digest).
    cache_invalidate(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_OUTCOMES_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_FUNNEL_CALIBRATION_CACHE_NAMESPACE,
        params={"project_id": project_id},
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
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
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
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

    return {
        "stored": True,
        "will_improve_model": will_learn,
        "learning_weight": round(learning_weight, 4),
        "signal_quality": sq,
        "accuracy_trend": trend,
        "message": (
            "Thank you — your outcome data improves TheCee for all founders."
            if will_learn
            else (
                "Stored but not used for calibration "
                "(signal quality too low or product changed since simulation)."
            )
        ),
    }


@router.post(
    "/{project_id}/outcome-tracker",
    response_model=OutcomeTrackerPoint,
    status_code=status.HTTP_201_CREATED,
    summary="Log a lightweight conversion-tracking checkpoint",
    # DB write — cap path-spam at 30/min/IP for the same reason as the
    # simulations POST limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def log_outcome_tracker_point(
    project_id: int,
    payload: OutcomeTrackerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerPoint:
    """Persist a conversion/revenue checkpoint for a project over time.

    Unlike the structured launch-outcome flow, this endpoint is meant for
    repeated lightweight checkpoints (week 1, week 4, etc.). Predicted values
    are auto-filled from the project's latest completed simulation unless a
    specific ``simulation_id`` is supplied.
    """
    get_owned_project(db, current_user.id, project_id)

    sim: Simulation | None = None
    if payload.simulation_id is not None:
        sim = (
            db.query(Simulation)
            .filter(
                Simulation.id == payload.simulation_id,
                Simulation.project_id == project_id,
            )
            .first()
        )
        if not sim:
            raise HTTPException(status_code=404, detail="Simulation not found")
    else:
        sim = (
            db.query(Simulation)
            .filter(
                Simulation.project_id == project_id,
                Simulation.status == "COMPLETED",
            )
            .order_by(Simulation.created_at.desc())
            .first()
        )

    pred_conv: float | None = None
    pred_rev: float | None = None
    sim_id: int | None = None
    if sim is not None and sim.results_json:
        pred_conv = _predicted_from_results(sim.results_json)
        pred_rev = _predicted_revenue_from_results(sim.results_json)
        sim_id = sim.id

    variance = None
    if payload.actual_conversion_rate is not None:
        variance = _variance_pct(payload.actual_conversion_rate, pred_conv)

    row = OutcomeTracker(
        project_id=project_id,
        simulation_id=sim_id,
        actual_conversion_rate=payload.actual_conversion_rate,
        actual_revenue=payload.actual_revenue,
        predicted_conversion_rate=pred_conv,
        predicted_revenue=pred_rev,
        variance=variance,
        notes=payload.notes,
        recorded_at=payload.recorded_at or datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _hydrate_tracker_point(row)


@router.get(
    "/{project_id}/outcome-tracker",
    response_model=OutcomeTrackerTimelineOut,
    summary="List conversion-tracking checkpoints for a project",
)
def get_outcome_tracker_timeline(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerTimelineOut:
    """Return the full tracking timeline plus derived calibration summary."""
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    payload = build_outcome_tracker_timeline(
        [r.__dict__ for r in rows],
        project_id=project_id,
    )
    return OutcomeTrackerTimelineOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/export",
    summary="Export a project's conversion-tracking checkpoints as CSV (or JSON)",
    response_class=StreamingResponse,
)
def export_outcome_tracker(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "checkpoint rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's conversion-tracking checkpoints."""
    get_owned_project(db, current_user.id, project_id)

    trackers = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    rows = [
        {
            "id": row.id,
            "project_id": row.project_id,
            "simulation_id": row.simulation_id,
            "recorded_at": row.recorded_at,
            "actual_conversion_rate": row.actual_conversion_rate,
            "actual_revenue": row.actual_revenue,
            "predicted_conversion_rate": row.predicted_conversion_rate,
            "predicted_revenue": row.predicted_revenue,
            "variance": row.variance,
            "notes": row.notes,
        }
        for row in trackers
    ]

    generated_at = datetime.now(UTC).isoformat()
    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": generated_at,
                "user_id": current_user.id,
                "project_id": project_id,
                "total": len(rows),
                "points": rows,
            },
            default=_json_default,
            indent=2,
        )
        body = json_text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="outcome-tracker-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = outcome_tracker_to_csv(
        rows,
        metadata={
            "generated_at": generated_at,
            "user_id": current_user.id,
            "project_id": project_id,
            "total": len(rows),
        },
    )
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="outcome-tracker-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.post(
    "/{project_id}/outcomes",
    response_model=OutcomeRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Record a structured launch outcome against the latest simulation",
    # DB write — cap path-spam at 30/min/IP for the same reason as
    # the simulations POST limit. Outcome records are written
    # manually by the founder post-launch.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def record_outcome(
    project_id: int,
    payload: OutcomeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    pred_conv: float | None = None
    pred_mrr: float | None = None
    sim_id: int | None = None

    if latest_sim and latest_sim.results_json:
        results = latest_sim.results_json
        maybe_conv = results.get("mean_conversion_rate") or results.get("conversion_rate")
        maybe_mrr = results.get("mean_revenue") or results.get("revenue_projection")
        pred_conv = float(maybe_conv) if maybe_conv is not None else None
        pred_mrr = float(maybe_mrr) if maybe_mrr is not None else None
        sim_id = latest_sim.id

    var_conv = _variance_pct(payload.actual_conversion_rate, pred_conv)
    var_mrr = _variance_pct(payload.actual_mrr, pred_mrr)
    var_cac = None
    var_churn = None

    cal_score = _calibration_score(
        actual_conv=payload.actual_conversion_rate,
        actual_mrr=payload.actual_mrr,
        actual_cac=payload.actual_cac,
        actual_churn=payload.actual_churn_rate,
        pred_conv=pred_conv,
        pred_mrr=pred_mrr,
    )

    outcome = Outcome(
        project_id=project_id,
        actual_conversion_rate=payload.actual_conversion_rate,
        actual_mrr=payload.actual_mrr,
        actual_cac=payload.actual_cac,
        actual_churn_rate=payload.actual_churn_rate,
        days_since_launch=payload.days_since_launch,
        actual_dau=payload.actual_dau,
        actual_nps=payload.actual_nps,
        notes=payload.notes,
        predicted_conversion_rate=pred_conv,
        predicted_mrr=pred_mrr,
        predicted_revenue=pred_mrr,
        simulation_id=sim_id,
        variance_conversion=var_conv,
        variance_mrr=var_mrr,
        variance_cac=var_cac,
        variance_churn=var_churn,
        calibration_score=cal_score,
    )
    db.add(outcome)

    project.status = "OUTCOME_RECORDED"
    db.commit()
    db.refresh(outcome)

    logger.info(
        "[Outcome] Recorded — project_id=%s actual_conv=%.3f pred_conv=%s calibration=%.1f",
        project_id,
        payload.actual_conversion_rate,
        pred_conv,
        cal_score,
    )
    # Bust the cached per-project next-action + the
    # activity feed + the outcomes digest so the
    # dashboard reflects the new outcome immediately.
    cache_invalidate(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_OUTCOMES_DIGEST_CACHE_NAMESPACE,
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
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
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
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    return _hydrate_record(outcome)


@router.get(
    "/{project_id}/outcomes",
    response_model=OutcomeHistoryOut,
    summary="List outcomes and calibration aggregates for a project",
)
def get_outcome_history(
    project_id: int,
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description=(
            "Max outcomes to return. Omit to return all matching "
            "outcomes (no pagination)."
        ),
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description=(
            "Number of matching outcomes to skip before returning "
            "the page."
        ),
    ),
    start_date: datetime | None = Query(
        default=None,
        description=(
            "Return outcomes recorded at or after this UTC datetime."
        ),
    ),
    end_date: datetime | None = Query(
        default=None,
        description=(
            "Return outcomes recorded at or before this UTC datetime."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_owned_project(db, current_user.id, project_id)

    start_date = _as_utc(start_date)
    end_date = _as_utc(end_date)

    base = db.query(Outcome).filter(Outcome.project_id == project_id)
    if start_date is not None:
        base = base.filter(Outcome.created_at >= start_date)
    if end_date is not None:
        base = base.filter(Outcome.created_at <= end_date)

    filtered_total = base.count()

    ordered = base.order_by(Outcome.created_at.desc())
    if limit is not None:
        rows = ordered.offset(offset).limit(limit + 1).all()
        has_more = len(rows) > limit
        outcomes = rows[:limit]
    else:
        outcomes = ordered.offset(offset).all()
        has_more = False

    # Calibration aggregates and trend are computed over the *full*
    # filtered set so paging never changes the headline numbers.
    avg_score, best_score, worst_score = (
        base.with_entities(
            func.avg(func.coalesce(Outcome.calibration_score, 0.0)),
            func.max(func.coalesce(Outcome.calibration_score, 0.0)),
            func.min(func.coalesce(Outcome.calibration_score, 0.0)),
        ).one()
    )
    trend = _calibration_trend(
        base.order_by(Outcome.created_at.desc()).limit(3).all()
    )

    records = [_hydrate_record(outcome) for outcome in outcomes]

    if not records:
        return OutcomeHistoryOut(
            project_id=project_id,
            outcomes=[],
            total=filtered_total,
            filtered_total=filtered_total,
            limit=limit,
            offset=offset,
            has_more=has_more,
            average_calibration_score=round(float(avg_score or 0.0), 2),
            best_calibration_score=round(float(best_score or 0.0), 2),
            worst_calibration_score=round(float(worst_score or 0.0), 2),
            calibration_trend=trend,
        )

    return OutcomeHistoryOut(
        project_id=project_id,
        outcomes=records,
        total=filtered_total,
        filtered_total=filtered_total,
        limit=limit,
        offset=offset,
        has_more=has_more,
        average_calibration_score=round(float(avg_score or 0.0), 2),
        best_calibration_score=round(float(best_score or 0.0), 2),
        worst_calibration_score=round(float(worst_score or 0.0), 2),
        calibration_trend=trend,
    )


@router.get(
    "/{project_id}/outcomes/export",
    summary="Export a project's outcome records as CSV (or JSON)",
    response_class=StreamingResponse,
)
def export_outcomes(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "outcome rows."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a project's outcome records."""
    get_owned_project(db, current_user.id, project_id)

    outcomes = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .all()
    )
    rows = [
        {
            "id": outcome.id,
            "project_id": outcome.project_id,
            "simulation_id": outcome.simulation_id,
            "created_at": outcome.created_at,
            "actual_conversion_rate": outcome.actual_conversion_rate,
            "actual_mrr": outcome.actual_mrr,
            "actual_cac": outcome.actual_cac,
            "actual_churn_rate": outcome.actual_churn_rate,
            "actual_dau": outcome.actual_dau,
            "actual_nps": outcome.actual_nps,
            "days_since_launch": outcome.days_since_launch,
            "notes": outcome.notes,
            "predicted_conversion_rate": outcome.predicted_conversion_rate,
            "predicted_mrr": outcome.predicted_mrr,
            "predicted_revenue": outcome.predicted_revenue,
            "variance_conversion": outcome.variance_conversion,
            "variance_mrr": outcome.variance_mrr,
            "variance_cac": outcome.variance_cac,
            "variance_churn": outcome.variance_churn,
            "calibration_score": outcome.calibration_score,
        }
        for outcome in outcomes
    ]

    fmt = format.strip().lower() if format else "csv"
    if fmt == "json":
        json_text = json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "project_id": project_id,
                "outcomes": rows,
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
                    f'attachment; filename="outcomes-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = outcomes_to_csv(rows)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="outcomes-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/outcomes/{outcome_id}",
    response_model=OutcomeRecord,
    summary="Get a single outcome record",
)
def get_single_outcome(
    project_id: int,
    outcome_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    outcome = (
        db.query(Outcome)
        .join(Project, Outcome.project_id == Project.id)
        .filter(
            Outcome.id == outcome_id,
            Outcome.project_id == project_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")

    return _hydrate_record(outcome)


@router.delete(
    "/{project_id}/outcomes/{outcome_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recorded outcome",
    responses={204: {"description": "Outcome deleted"}},
    # Destructive — cap path-spam at 10/min/IP so a runaway script
    # can't churn through deletes.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def delete_outcome(
    project_id: int,
    outcome_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    outcome = (
        db.query(Outcome)
        .join(Project, Outcome.project_id == Project.id)
        .filter(
            Outcome.id == outcome_id,
            Outcome.project_id == project_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")

    db.delete(outcome)
    db.commit()

    # Bust the per-project outcomes-digest so the deleted
    # outcome disappears from MAE / bias / trend numbers
    # immediately rather than waiting out the 120s TTL.
    # Also bust /me/dashboard + /me/account-health + the
    # per-project health score: outcome_count +
    # calibration health + health-score inputs all shift
    # on every delete.
    cache_invalidate(
        namespace=_OUTCOMES_DIGEST_CACHE_NAMESPACE,
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
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_STALE_CHECK_CACHE_NAMESPACE,
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
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
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
        namespace=_USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
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
    cache_invalidate(
        namespace=_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )


@router.get(
    "/{project_id}/outcomes-digest",
    response_model=OutcomeDigestOut,
    summary=(
        "Per-project outcomes digest — composes outcomes + "
        "leaderboard + calibration health into a single "
        "'how trustable are my numbers?' payload"
    ),
    # Read-only aggregation; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_outcomes_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeDigestOut:
    """Per-project outcomes digest.

    Composes ``build_outcomes_digest`` from:

    * The project's recorded ``Outcome`` rows (predicted /
      actual conversion-rate pairs).
    * The ``bridge_architect_accuracy`` output, reused
      from the calibration-health pipeline.
    * The ``build_calibration_health`` output.

    Avoids fanning out to /portfolio-summary,
    /calibration-health, and /architect-leaderboard on the
    dashboard's project-overview tile.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the four queries.
    cached = cache_get_json(
        namespace=_OUTCOMES_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return OutcomeDigestOut(**cached)

    # Pull the prediction pairs (newest first).
    outcome_rows = (
        db.query(
            Outcome.created_at,
            Outcome.predicted_conversion_rate,
            Outcome.actual_conversion_rate,
            Outcome.simulation_id,
            Simulation.results_json,
        )
        .outerjoin(
            Simulation, Simulation.id == Outcome.simulation_id,
        )
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .all()
    )
    pairs: list[tuple[float | None, float | None]] = []
    outcome_pairs: list[
        tuple[list[dict], tuple[float | None, float | None]]
    ] = []
    health_rows: list[tuple] = []
    for r in outcome_rows:
        domain_findings = (
            (r.results_json or {}).get("domain_findings") or []
        )
        pairs.append(
            (r.predicted_conversion_rate,
             r.actual_conversion_rate),
        )
        outcome_pairs.append(
            (domain_findings,
             (r.predicted_conversion_rate,
              r.actual_conversion_rate)),
        )
        health_rows.append(
            (
                r.created_at,
                r.predicted_conversion_rate,
                r.actual_conversion_rate,
                domain_findings,
            ),
        )

    # Architect leaderboard from the bridge output.
    bridge = bridge_architect_accuracy(outcome_pairs)
    leaderboard = build_architect_leaderboard(
        bridge.get("by_architect"),
    )

    # Calibration health verdict.
    calibration_health = (
        build_calibration_health(health_rows)
        if health_rows else None
    )

    payload = build_outcomes_digest(
        prediction_pairs=pairs,
        architect_leaderboard=leaderboard.get("leaderboard"),
        calibration_health=calibration_health,
    )
    cache_set_json(
        namespace=_OUTCOMES_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=120,
    )
    return OutcomeDigestOut(**payload)


@router.get(
    "/{project_id}/funnel-calibration-digest",
    response_model=FunnelCalibrationDigestOut,
    summary=(
        "Per-project funnel calibration digest — compares simulated "
        "stage drop-off against actual founder-reported drop-off"
    ),
    # Read-only aggregation over the calibration learning layer; bounded.
    dependencies=[Depends(rate_limit(limit=60, window_s=60))],
)
def get_funnel_calibration_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FunnelCalibrationDigestOut:
    """Per-project funnel calibration digest.

    Cross-references the simulation's predicted ``BROWSE`` / ``CONSIDER`` /
    ``DECIDE`` drop-off rates with the actual drop-off rates founders
    recorded on calibration-eligible ``founder_outcomes`` (validated rows
    with ``learning_weight > 0``) so the dashboard can show exactly which
    funnel stage the simulation is mis-predicting.
    """
    get_owned_project(db, current_user.id, project_id)

    cached = cache_get_json(
        namespace=_FUNNEL_CALIBRATION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return FunnelCalibrationDigestOut(**cached)

    rows = db.execute(
        text("""
            SELECT
                s.results_json,
                fo.actual_drop_at_browse_pct,
                fo.actual_drop_at_consider_pct,
                fo.actual_drop_at_decide_pct
            FROM founder_outcomes fo
            JOIN simulations s ON s.id = fo.simulation_id
            JOIN projects p ON p.id = fo.project_id
            WHERE fo.project_id = :pid
              AND p.user_id = :uid
              AND fo.validated = true
              AND fo.learning_weight > 0
            ORDER BY fo.created_at DESC, fo.id DESC
            LIMIT 50
        """),
        {"pid": project_id, "uid": current_user.id},
    ).mappings().all()

    pairs: list[tuple[object | None, dict[str, float | None]]] = []
    for row in rows:
        pairs.append(
            (
                row.get("results_json"),
                {
                    "BROWSE": row.get("actual_drop_at_browse_pct"),
                    "CONSIDER": row.get("actual_drop_at_consider_pct"),
                    "DECIDE": row.get("actual_drop_at_decide_pct"),
                },
            )
        )

    payload = build_funnel_calibration_digest(pairs)
    cache_set_json(
        namespace=_FUNNEL_CALIBRATION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=120,
    )
    return FunnelCalibrationDigestOut(**payload)


@router.get(
    "/{project_id}/outcome-benchmark",
    response_model=OutcomeBenchmarkOut,
    summary=(
        "Benchmark a project's real-world conversion against other "
        "launched outcomes in the same product category"
    ),
    # Read-only aggregate over the calibration learning layer; bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_outcome_benchmark(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeBenchmarkOut:
    """Rank one project's reported outcome against peer launches.

    Uses the most recent ``founder_outcomes`` row for the project, derives
    the product category from the linked simulation (falling back to the
    project's latest completed simulation), and compares the actual
    conversion rate against other launched outcomes in that category.
    Only aggregates are returned — individual peer rows are never exposed.
    """
    get_owned_project(db, current_user.id, project_id)

    current_row = db.execute(
        text("""
            SELECT
                fo.id,
                fo.simulation_id,
                fo.project_id,
                fo.days_since_launch,
                fo.actual_conversion_rate,
                fo.launched,
                fo.data_confidence,
                fo.created_at,
                s.results_json,
                s.results_json->>'product_type_detected' AS product_type_detected
            FROM founder_outcomes fo
            LEFT JOIN simulations s ON s.id = fo.simulation_id
            WHERE fo.project_id = :pid
            ORDER BY fo.created_at DESC, fo.id DESC
            LIMIT 1
        """),
        {"pid": project_id},
    ).mappings().first()

    category = None
    current_outcome = None
    if current_row is not None:
        category = current_row.get("product_type_detected")
        current_outcome = {
            "outcome_id": current_row.get("id"),
            "simulation_id": current_row.get("simulation_id"),
            "project_id": current_row.get("project_id"),
            "days_since_launch": current_row.get("days_since_launch"),
            "actual_conversion_rate": current_row.get(
                "actual_conversion_rate"
            ),
            "predicted_conversion_rate": predicted_conversion_from_results(
                current_row.get("results_json")
            ),
            "launched": current_row.get("launched"),
            "data_confidence": current_row.get("data_confidence"),
            "created_at": current_row.get("created_at"),
        }

    if category is None or not str(category).strip():
        fallback = db.execute(
            text("""
                SELECT
                    results_json->>'product_type_detected'
                        AS product_type_detected
                FROM simulations
                WHERE project_id = :pid
                  AND UPPER(status) = 'COMPLETED'
                  AND results_json->>'product_type_detected' IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"pid": project_id},
        ).mappings().first()
        if fallback is not None:
            category = fallback.get("product_type_detected")

    peer_rows: list[dict] = []
    if category and str(category).strip():
        peer_rows = [
            dict(row)
            for row in db.execute(
                text("""
                    SELECT
                        fo.actual_conversion_rate,
                        COALESCE(
                            fo.product_changed_since_sim,
                            FALSE
                        ) AS product_changed_since_sim
                    FROM founder_outcomes fo
                    JOIN simulations s ON s.id = fo.simulation_id
                    JOIN projects p ON p.id = fo.project_id
                    WHERE p.id <> :pid
                      AND COALESCE(fo.launched, FALSE) = TRUE
                      AND s.results_json->>'product_type_detected' = :pt
                    ORDER BY fo.created_at DESC, fo.id DESC
                    LIMIT :limit
                """),
                {
                    "pid": project_id,
                    "pt": str(category),
                    "limit": MAX_PEERS,
                },
            ).mappings().all()
        ]

    payload = build_outcome_benchmark(
        current_outcome,
        peer_rows,
        category=category,
    )
    return OutcomeBenchmarkOut(**payload)
