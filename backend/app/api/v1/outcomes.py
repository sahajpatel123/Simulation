from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
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
    _USER_INSIGHTS_CACHE_NAMESPACE,
    _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
    _USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
    _USER_NOTIFICATIONS_CACHE_NAMESPACE,
    _USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
    _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
    _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
    _USER_QUICK_STATS_CACHE_NAMESPACE,
    _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
    _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
)
from app.api.v1.projects import (
    _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
)
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.outcome import (
    OutcomeCreate,
    OutcomeDigestOut,
    OutcomeFeedbackRequest,
    OutcomeHistoryOut,
    OutcomeRecord,
    VarianceReport,
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
from app.simulation.outcomes_digest_v2 import (
    build_outcomes_digest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["outcomes"])

# Outcomes digest cache — single source of truth so
# future rename propagates to every invalidation site.
# 120s TTL matches the digest's internal cache.
_OUTCOMES_DIGEST_CACHE_NAMESPACE: str = "project-outcomes-digest"

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

    project = get_owned_project(db, current_user.id, project_id)

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    outcomes = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .all()
    )
    records = [_hydrate_record(outcome) for outcome in outcomes]

    if not records:
        return OutcomeHistoryOut(
            project_id=project_id,
            outcomes=[],
            total=0,
            average_calibration_score=0.0,
            best_calibration_score=0.0,
            worst_calibration_score=0.0,
            calibration_trend="INSUFFICIENT_DATA",
        )

    scores = [record.calibration_score for record in records]
    return OutcomeHistoryOut(
        project_id=project_id,
        outcomes=records,
        total=len(records),
        average_calibration_score=round(sum(scores) / len(scores), 2),
        best_calibration_score=round(max(scores), 2),
        worst_calibration_score=round(min(scores), 2),
        calibration_trend=_calibration_trend(outcomes),
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
