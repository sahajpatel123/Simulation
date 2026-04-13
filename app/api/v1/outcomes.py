from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.outcome import (
    OutcomeCreate,
    OutcomeHistoryOut,
    OutcomeRecord,
    VarianceReport,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["outcomes"])

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


@router.post("/{project_id}/outcome-feedback")
def submit_outcome_feedback(
    project_id: int,
    body: dict,
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

    simulation_id = body.get("simulation_id")
    actual_cr = body.get("actual_conversion_rate")

    if simulation_id is None or actual_cr is None:
        raise HTTPException(
            status_code=400,
            detail="simulation_id and actual_conversion_rate are required",
        )

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sim = (
        db.query(Simulation)
        .filter(Simulation.id == simulation_id, Simulation.project_id == project_id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")

    actual_cr = float(actual_cr)
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
    data_confidence = str(body.get("data_confidence", "ESTIMATED")).upper()
    product_changed = bool(body.get("product_changed_since_sim", False))
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
            "days": int(body.get("days_since_launch", 90)),
            "acr": actual_cr,
            "br": body.get("actual_drop_at_browse_pct"),
            "cr_val": body.get("actual_drop_at_consider_pct"),
            "dr": body.get("actual_drop_at_decide_pct"),
            "pfr": body.get("primary_failure_reason"),
            "pc": product_changed,
            "pricing": bool(body.get("pricing_changed", False)),
            "tm": bool(body.get("target_market_changed", False)),
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
)
def record_outcome(
    project_id: int,
    payload: OutcomeCreate,
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
    return _hydrate_record(outcome)


@router.get("/{project_id}/outcomes", response_model=OutcomeHistoryOut)
def get_outcome_history(
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


@router.get("/{project_id}/outcomes/{outcome_id}", response_model=OutcomeRecord)
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
