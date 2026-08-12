from __future__ import annotations

import json
import logging
import math
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
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
from app.schemas.failure_attribution import FailureAttributionOut
from app.schemas.funnel_calibration import FunnelCalibrationDigestOut
from app.schemas.outcome import (
    OutcomeBatchCreate,
    OutcomeBatchItem,
    OutcomeBatchOut,
    OutcomeCreate,
    OutcomeCsvImportOut,
    OutcomeDigestOut,
    OutcomeFeedbackRequest,
    OutcomeHistoryOut,
    OutcomeRecord,
    VarianceReport,
)
from app.schemas.outcome_benchmark import OutcomeBenchmarkOut
from app.schemas.outcome_gaps import ProjectOutcomeGapsOut
from app.schemas.outcome_tracker import (
    OutcomeTrackerCreate,
    OutcomeTrackerDriftOut,
    OutcomeTrackerForecastAccuracyOut,
    OutcomeTrackerForecastOut,
    OutcomeTrackerGoalPacingOut,
    OutcomeTrackerPoint,
    OutcomeTrackerRevenueForecastAccuracyOut,
    OutcomeTrackerRevenueForecastOut,
    OutcomeTrackerTimelineOut,
    OutcomeTrackerUpdate,
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
from app.simulation.failure_attribution import (
    build_failure_attribution,
)
from app.simulation.failure_attribution_export import (
    FORMAT_VERSION as FAILURE_ATTRIBUTION_FORMAT_VERSION,
)
from app.simulation.failure_attribution_export import (
    failure_attribution_to_csv,
    failure_attribution_to_json,
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
from app.simulation.outcome_benchmark_export import (
    FORMAT_VERSION as OUTCOME_BENCHMARK_FORMAT_VERSION,
)
from app.simulation.outcome_benchmark_export import (
    outcome_benchmark_to_csv,
    outcome_benchmark_to_json,
)
from app.simulation.outcome_gaps import build_outcome_gaps_digest
from app.simulation.outcome_gaps_export import (
    FORMAT_VERSION as OUTCOME_GAPS_FORMAT_VERSION,
)
from app.simulation.outcome_gaps_export import (
    outcome_gaps_to_csv,
    outcome_gaps_to_json,
    outcome_gaps_to_markdown,
)
from app.simulation.outcome_tracker_drift import (
    build_outcome_tracker_drift,
)
from app.simulation.outcome_tracker_export import (
    outcome_tracker_to_csv,
)
from app.simulation.outcome_tracker_forecast import (
    build_outcome_tracker_forecast,
)
from app.simulation.outcome_tracker_forecast_accuracy import (
    build_outcome_tracker_forecast_accuracy,
)
from app.simulation.outcome_tracker_goal_pacing import (
    build_outcome_tracker_goal_pacing,
)
from app.simulation.outcome_tracker_read import (
    build_outcome_tracker_timeline,
)
from app.simulation.outcome_tracker_revenue_forecast import (
    build_outcome_tracker_revenue_forecast,
)
from app.simulation.outcome_tracker_revenue_forecast_accuracy import (
    build_outcome_tracker_revenue_forecast_accuracy,
)
from app.simulation.outcomes_csv_import import parse_outcomes_csv
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


def _load_failure_attribution_rows(
    db: Session,
    project_id: int,
) -> list[dict[str, Any]]:
    """Load a project's founder outcomes for the failure-attribution digest.

    Left-joins the owning simulation so the builder can extract the
    predicted conversion even when the outcome predates the learning-layer
    ``signal_quality_at_run`` column or the simulation is later deleted.
    """
    rows_raw = db.execute(
        text(
            """
            SELECT
                fo.id,
                fo.simulation_id,
                fo.project_id,
                fo.days_since_launch,
                fo.actual_conversion_rate,
                fo.primary_failure_reason,
                fo.product_changed_since_sim,
                fo.pricing_changed,
                fo.target_market_changed,
                fo.data_confidence,
                COALESCE(fo.signal_quality_at_run, s.signal_quality)
                    AS signal_quality_at_run,
                fo.learning_weight,
                s.results_json
            FROM founder_outcomes fo
            LEFT JOIN simulations s ON s.id = fo.simulation_id
            WHERE fo.project_id = :pid
            ORDER BY fo.created_at DESC, fo.id DESC
            """
        ),
        {"pid": project_id},
    ).mappings().all()
    return [dict(row) for row in rows_raw]


# Outcomes digest cache — single source of truth so
# future rename propagates to every invalidation site.
# 120s TTL matches the digest's internal cache.
_OUTCOMES_DIGEST_CACHE_NAMESPACE: str = "project-outcomes-digest"
_FUNNEL_CALIBRATION_CACHE_NAMESPACE: str = "project-funnel-calibration"
_FAILURE_ATTRIBUTION_CACHE_NAMESPACE: str = "project-failure-attribution"

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

# Max accepted CSV upload size (1 MiB). 100 outcome rows fit comfortably in
# a fraction of this; the cap exists to keep the multipart body bounded.
MAX_CSV_BYTES: int = 1_048_576

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
        client_request_id=getattr(outcome, "client_request_id", None),
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


def _prediction_columns(
    sim: Simulation | None,
) -> tuple[float | None, float | None, int | None]:
    """Extract ``(predicted_conversion, predicted_mrr, simulation_id)``.

    Mirrors the single-record endpoint's extraction exactly: a simulation
    only contributes predictions when it is completed and carries a
    ``results_json`` payload; otherwise the row is recorded without
    predictions (variance stays ``None``) rather than fabricating zeros.

    Canonical keys are preferred and only fall back to legacy keys when
    they are absent — a genuine ``0.0`` prediction is kept so a zero
    forecast is not silently treated as "no prediction". Malformed or
    non-finite values are treated as missing instead of crashing the
    route or persisting NaN/Infinity into the outcomes table.
    """
    if sim is None or not sim.results_json:
        return None, None, None
    results = sim.results_json
    if not isinstance(results, dict):
        return None, None, None
    raw_conv = results.get("mean_conversion_rate")
    if raw_conv is None:
        raw_conv = results.get("conversion_rate")
    raw_mrr = results.get("mean_revenue")
    if raw_mrr is None:
        raw_mrr = results.get("revenue_projection")
    return (
        _safe_prediction_float(raw_conv),
        _safe_prediction_float(raw_mrr),
        sim.id,
    )


def _safe_prediction_float(value: Any) -> float | None:
    """Coerce a ``results_json`` value to a finite float, or ``None``.

    ``None``, booleans, non-numeric strings and non-finite values (NaN /
    Infinity) are treated as missing so a malformed legacy payload can
    neither crash outcome recording nor persist a non-serializable
    prediction. Zero is a legitimate prediction and is preserved; callers
    that cannot divide by zero already guard with ``predicted == 0.0``.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _build_outcome_row(
    project_id: int,
    payload: OutcomeCreate,
    pred_conv: float | None,
    pred_mrr: float | None,
    sim_id: int | None,
    client_request_id: str | None = None,
) -> Outcome:
    """Build a hydrated ``Outcome`` row from validated input + predictions."""
    var_conv = _variance_pct(payload.actual_conversion_rate, pred_conv)
    var_mrr = _variance_pct(payload.actual_mrr, pred_mrr)
    cal_score = _calibration_score(
        actual_conv=payload.actual_conversion_rate,
        actual_mrr=payload.actual_mrr,
        actual_cac=payload.actual_cac,
        actual_churn=payload.actual_churn_rate,
        pred_conv=pred_conv,
        pred_mrr=pred_mrr,
    )
    return Outcome(
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
        variance_cac=None,
        variance_churn=None,
        calibration_score=cal_score,
        client_request_id=client_request_id,
    )


def _existing_outcome_by_client_key(
    db: Session,
    project_id: int,
    client_request_id: str | None,
) -> Outcome | None:
    """Return the previously recorded outcome for an idempotency key."""
    if client_request_id is None:
        return None
    return (
        db.query(Outcome)
        .filter(
            Outcome.project_id == project_id,
            Outcome.client_request_id == client_request_id,
        )
        .first()
    )


def _existing_outcomes_by_client_key(
    db: Session,
    project_id: int,
    client_request_id: set[str],
) -> dict[str, Outcome]:
    """Map previously recorded outcomes by idempotency key."""
    if not client_request_id:
        return {}
    rows = (
        db.query(Outcome)
        .filter(
            Outcome.project_id == project_id,
            Outcome.client_request_id.in_(sorted(client_request_id)),
        )
        .all()
    )
    return {
        str(row.client_request_id): row
        for row in rows
        if row.client_request_id is not None
    }


def _resolve_batch_rows(
    project_id: int,
    items: list[OutcomeBatchItem],
    sim_by_id: dict[int, Simulation],
    latest_sim: Simulation | None,
    existing_by_key: dict[str, Outcome],
) -> tuple[list[Outcome], list[Outcome]]:
    """Split batch items into rows to create and already-recorded replays.

    Every item whose ``client_request_id`` already exists is a replay: the
    original record wins and is echoed back unchanged. New rows are built
    with the same prediction binding as before (explicit simulation when
    supplied, otherwise the project's latest completed simulation).
    """
    new_rows: list[Outcome] = []
    replayed: list[Outcome] = []
    for item in items:
        existing = (
            existing_by_key.get(item.client_request_id)
            if item.client_request_id is not None
            else None
        )
        if existing is not None:
            replayed.append(existing)
            continue
        if item.simulation_id is not None:
            sim = sim_by_id[item.simulation_id]
            if sim.status != "COMPLETED" or not sim.results_json:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"simulation_id {item.simulation_id} is not "
                        "completed with results."
                    ),
                )
            pred_conv, pred_mrr, sim_id = _prediction_columns(sim)
        else:
            pred_conv, pred_mrr, sim_id = _prediction_columns(latest_sim)
        new_rows.append(
            _build_outcome_row(
                project_id=project_id,
                payload=item,
                pred_conv=pred_conv,
                pred_mrr=pred_mrr,
                sim_id=sim_id,
                client_request_id=item.client_request_id,
            )
        )
    return new_rows, replayed


def _batch_replay_response(
    project_id: int,
    replayed: list[Outcome],
) -> OutcomeBatchOut:
    """Build a pure-replay batch response when nothing new was written."""
    return OutcomeBatchOut(
        project_id=project_id,
        created_count=0,
        replayed_count=len(replayed),
        outcomes=[_hydrate_record(outcome) for outcome in replayed],
    )


def _csv_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Map a Pydantic batch-validation failure onto CSV row numbers.

    ``OutcomeBatchCreate`` reports errors with ``loc`` tuples like
    ``("outcomes", 0, "actual_conversion_rate")``; the integer segment is
    the batch index, which corresponds to CSV data row ``2 + index``
    because the header is row 1.
    """
    rows: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        row = 2
        column: str | None = None
        for part in loc:
            if isinstance(part, int) and part >= 0:
                row = 2 + part
            elif isinstance(part, str):
                column = part
        rows.append(
            {
                "row": row,
                "column": column,
                "error": err.get("msg", "invalid value"),
            }
        )
    return rows


def _latest_tracker_conversion_target(
    rows: list[OutcomeTracker],
    sim: Simulation | None,
) -> float | None:
    """Resolve the conversion target shared by the tracker forecast routes.

    Prefers the newest completed simulation's predicted conversion rate;
    when no usable simulation exists, falls back to the newest legacy
    checkpoint's captured prediction (rows arrive in ascending
    ``recorded_at`` order).
    """
    if sim is not None and sim.results_json:
        raw_pred = _predicted_from_results(sim.results_json)
        if raw_pred and raw_pred > 0.0:
            return float(raw_pred)
    for row in reversed(rows):
        if row.predicted_conversion_rate and row.predicted_conversion_rate > 0.0:
            return float(row.predicted_conversion_rate)
    return None


def _latest_tracker_revenue_target(
    rows: list[OutcomeTracker],
    sim: Simulation | None,
) -> float | None:
    """Resolve the revenue target shared by the tracker revenue routes.

    Prefers the newest completed simulation's predicted revenue; when no
    usable simulation exists, falls back to the newest legacy checkpoint's
    captured prediction (rows arrive in ascending ``recorded_at`` order).
    """
    if sim is not None and sim.results_json:
        raw_pred = _predicted_revenue_from_results(sim.results_json)
        if raw_pred is not None and raw_pred > 0.0:
            return float(raw_pred)
    for row in reversed(rows):
        if row.predicted_revenue and row.predicted_revenue > 0.0:
            return float(row.predicted_revenue)
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
    Celery if new effective_sample_count crosses the activation threshold (10),
    and Layer 5 via Celery once any cluster crosses its trait-calibration
    effective-sample threshold (5).
    """
    from app.simulation.calibration_engine import CalibrationEngine
    from app.tasks.calibration_tasks import (
        run_cluster_trait_calibration,
        run_funnel_stage_calibration,
        run_systematic_bias_update,
    )

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

    # ── Check whether Layer 5 threshold is crossed → fire Celery task ──
    try:
        if eng.clusters_ready_for_trait_calibration(db):
            run_cluster_trait_calibration.delay()
            logger.info(
                "[OutcomeFeedback] Triggered cluster trait calibration "
                "(a cluster crossed the effective-sample threshold)"
            )
    except Exception as exc:
        logger.warning(
            "[OutcomeFeedback] Could not trigger cluster trait calibration: %s",
            exc,
        )

    # ── Check whether Layer 6 has per-stage evidence → fire Celery task ──
    try:
        if eng.funnel_stage_calibration_ready(db):
            run_funnel_stage_calibration.delay()
            logger.info(
                "[OutcomeFeedback] Triggered funnel stage calibration "
                "(validated outcome carries per-stage drop-offs)"
            )
    except Exception as exc:
        logger.warning(
            "[OutcomeFeedback] Could not trigger funnel stage calibration: %s",
            exc,
        )

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
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_FAILURE_ATTRIBUTION_CACHE_NAMESPACE,
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


@router.patch(
    "/{project_id}/outcome-tracker/{point_id}",
    response_model=OutcomeTrackerPoint,
    summary="Correct a logged conversion-tracking checkpoint",
    # DB write — cap path-spam at 30/min/IP for the same reason as the
    # simulations POST limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def update_outcome_tracker_point(
    project_id: int,
    point_id: int,
    payload: OutcomeTrackerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerPoint:
    """Fix a mis-entered conversion/revenue checkpoint in place.

    Omitted fields stay untouched, so a founder can correct a typo in one
    field (e.g. ``recorded_at``) without losing the rest of the row. When a
    ``simulation_id`` is supplied the predicted values are recomputed from
    that simulation; otherwise the checkpoint's captured prediction is kept.
    The stored ``variance`` is always recomputed from the merged values so
    the drift / forecast / accuracy endpoints never serve stale numbers.
    """
    get_owned_project(db, current_user.id, project_id)

    row = (
        db.query(OutcomeTracker)
        .filter(
            OutcomeTracker.id == point_id,
            OutcomeTracker.project_id == project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Outcome tracker point not found",
        )

    if "simulation_id" in payload.model_fields_set:
        if payload.simulation_id is None:
            # Explicit detach: drop the simulation link and its predictions
            # so the checkpoint no longer claims a captured target.
            row.simulation_id = None
            row.predicted_conversion_rate = None
            row.predicted_revenue = None
        else:
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
            row.simulation_id = sim.id
            if sim.results_json:
                row.predicted_conversion_rate = _predicted_from_results(sim.results_json)
                row.predicted_revenue = _predicted_revenue_from_results(sim.results_json)
            else:
                row.predicted_conversion_rate = None
                row.predicted_revenue = None

    if "actual_conversion_rate" in payload.model_fields_set:
        row.actual_conversion_rate = payload.actual_conversion_rate
    if "actual_revenue" in payload.model_fields_set:
        row.actual_revenue = payload.actual_revenue
    if "recorded_at" in payload.model_fields_set:
        row.recorded_at = payload.recorded_at
    if "notes" in payload.model_fields_set:
        row.notes = payload.notes

    if row.actual_conversion_rate is None and row.actual_revenue is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "A checkpoint must keep at least one of "
                "actual_conversion_rate or actual_revenue"
            ),
        )

    # Recompute from the merged values so a simulation change or a cleared
    # conversion rate can never leave a stale variance behind.
    row.variance = (
        _variance_pct(row.actual_conversion_rate, row.predicted_conversion_rate)
        if row.actual_conversion_rate is not None
        and row.predicted_conversion_rate is not None
        else None
    )

    db.commit()
    db.refresh(row)
    return _hydrate_tracker_point(row)


@router.delete(
    "/{project_id}/outcome-tracker/{point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a logged conversion-tracking checkpoint",
    responses={204: {"description": "Outcome tracker point deleted"}},
    # Destructive — cap path-spam at 10/min/IP so a runaway script
    # can't churn through deletes.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def delete_outcome_tracker_point(
    project_id: int,
    point_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Remove a mis-logged checkpoint so it stops skewing tracker insights."""
    get_owned_project(db, current_user.id, project_id)

    row = (
        db.query(OutcomeTracker)
        .filter(
            OutcomeTracker.id == point_id,
            OutcomeTracker.project_id == project_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Outcome tracker point not found",
        )

    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    "/{project_id}/outcome-tracker/forecast",
    response_model=OutcomeTrackerForecastOut,
    summary="Forecast post-launch conversion trajectory from tracking checkpoints",
)
def get_outcome_tracker_forecast(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerForecastOut:
    """Predict where the project's post-launch conversion is heading.

    Fits a deterministic trend over the logged conversion checkpoints and
    compares the 30-day projection (or the latest actual, when it already
    meets the prediction) against the project's latest simulation
    prediction. The route supplies the checkpoint rows and prediction; all
    arithmetic lives in the pure helper module.
    """
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    predicted = _latest_tracker_conversion_target(rows, sim)

    payload = build_outcome_tracker_forecast(
        [r.__dict__ for r in rows],
        project_id=project_id,
        predicted_conversion_rate=predicted,
    )
    return OutcomeTrackerForecastOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/revenue-forecast",
    response_model=OutcomeTrackerRevenueForecastOut,
    summary="Forecast post-launch revenue trajectory from tracking checkpoints",
)
def get_outcome_tracker_revenue_forecast(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerRevenueForecastOut:
    """Predict where the project's post-launch revenue is heading.

    Fits a deterministic trend over the logged revenue checkpoints and
    compares the 30-day projection (or the latest actual, when it already
    meets the prediction) against the project's latest simulation revenue
    prediction. The route supplies the checkpoint rows and prediction; all
    arithmetic lives in the pure helper module.
    """
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    predicted = _latest_tracker_revenue_target(rows, sim)

    payload = build_outcome_tracker_revenue_forecast(
        [r.__dict__ for r in rows],
        project_id=project_id,
        predicted_revenue=predicted,
    )
    return OutcomeTrackerRevenueForecastOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/revenue-forecast-accuracy",
    response_model=OutcomeTrackerRevenueForecastAccuracyOut,
    summary="Verify historical revenue-forecast accuracy from tracking checkpoints",
)
def get_outcome_tracker_revenue_forecast_accuracy(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerRevenueForecastAccuracyOut:
    """Measure how reliable the revenue forecast has been over time.

    Rebuilds the 30/60/90-day revenue projection the production builder
    would have produced at each historical checkpoint and compares it with
    what actually happened later, so a founder can see whether the revenue
    trajectory has been accurate, and whether it systematically over- or
    under-predicts.
    """
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    predicted = _latest_tracker_revenue_target(rows, sim)

    payload = build_outcome_tracker_revenue_forecast_accuracy(
        [r.__dict__ for r in rows],
        project_id=project_id,
        predicted_revenue=predicted,
    )
    return OutcomeTrackerRevenueForecastAccuracyOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/forecast-accuracy",
    response_model=OutcomeTrackerForecastAccuracyOut,
    summary="Verify historical trajectory-forecast accuracy from tracking checkpoints",
)
def get_outcome_tracker_forecast_accuracy(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerForecastAccuracyOut:
    """Measure how reliable the trajectory forecast has been over time.

    Rebuilds the 30/60/90-day forecast the production builder would have
    produced at each historical checkpoint and compares it with what
    actually happened later, so a founder can see whether the model has
    been accurate, and whether it systematically over- or under-predicts.
    """
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    predicted = _latest_tracker_conversion_target(rows, sim)

    payload = build_outcome_tracker_forecast_accuracy(
        [r.__dict__ for r in rows],
        project_id=project_id,
        predicted_conversion_rate=predicted,
    )
    return OutcomeTrackerForecastAccuracyOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/drift",
    response_model=OutcomeTrackerDriftOut,
    summary="Detect post-launch conversion drift versus the model's expected path",
)
def get_outcome_tracker_drift(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerDriftOut:
    """Early-warning signal for divergence between actual and expected conversion.

    Rebuilds the projection the trajectory forecast would have made at each
    checkpoint, compares it with the conversion actually logged at the next
    checkpoint, and reports whether the project is tracking, ahead of, or
    behind the model's expected path — plus whether any gap is widening,
    narrowing, or stable.
    """
    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    predicted = _latest_tracker_conversion_target(rows, sim)

    payload = build_outcome_tracker_drift(
        [r.__dict__ for r in rows],
        project_id=project_id,
        predicted_conversion_rate=predicted,
    )
    return OutcomeTrackerDriftOut(**payload)


@router.get(
    "/{project_id}/outcome-tracker/goal-pacing",
    response_model=OutcomeTrackerGoalPacingOut,
    summary="Check whether tracked conversion/revenue will hit founder-set goals by a deadline",
)
def get_outcome_tracker_goal_pacing(
    project_id: int,
    target_conversion_rate: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description=(
            "Founder-set conversion goal in [0, 1]. Provide at least one "
            "of target_conversion_rate / target_revenue."
        ),
    ),
    target_revenue: float | None = Query(
        default=None,
        ge=0.0,
        allow_inf_nan=False,
        description=(
            "Founder-set revenue goal (non-negative currency). Provide at "
            "least one of target_conversion_rate / target_revenue."
        ),
    ),
    deadline: date | None = Query(
        default=None,
        description=(
            "ISO date (YYYY-MM-DD) by which the goal should be reached. "
            "Omit to get trend-based days-to-goal only."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeTrackerGoalPacingOut:
    """Evaluate pacing toward a founder's own conversion/revenue goals.

    Fits the same deterministic linear trend used by the trajectory
    forecasts, then answers the question those endpoints do not: will the
    tracked metric reach the founder's *own* target by the founder's
    deadline — and how much faster does growth need to be? Supports
    conversion and/or revenue goals in one call; all arithmetic lives in
    the pure helper module.
    """
    if target_conversion_rate is None and target_revenue is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Provide at least one of target_conversion_rate or "
                "target_revenue"
            ),
        )
    if target_conversion_rate is not None and target_conversion_rate <= 0.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_conversion_rate must be greater than 0",
        )
    if target_revenue is not None and target_revenue <= 0.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_revenue must be greater than 0",
        )

    get_owned_project(db, current_user.id, project_id)

    rows = (
        db.query(OutcomeTracker)
        .filter(OutcomeTracker.project_id == project_id)
        .order_by(OutcomeTracker.recorded_at.asc())
        .all()
    )
    payload = build_outcome_tracker_goal_pacing(
        [r.__dict__ for r in rows],
        project_id=project_id,
        target_conversion_rate=target_conversion_rate,
        target_revenue=target_revenue,
        deadline=deadline,
    )
    return OutcomeTrackerGoalPacingOut(**payload)


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


def _invalidate_outcome_caches(user_id: int) -> None:
    """Bust every cached dashboard tile that derives from outcome state.

    Single outcome records and batch imports mutate the same surfaces, so
    both routes share one invalidation pass. Namespaces are deduplicated —
    invalidating a Redis key twice is idempotent, so the net effect matches
    the original single-record route exactly with fewer round-trips.
    """
    for namespace in (
        _NEXT_ACTION_CACHE_NAMESPACE,
        _ACTIVITY_FEED_CACHE_NAMESPACE,
        _OUTCOMES_DIGEST_CACHE_NAMESPACE,
        _USER_DASHBOARD_CACHE_NAMESPACE,
        _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
        _PROJECT_HEALTH_CACHE_NAMESPACE,
        _LATEST_SNAPSHOT_CACHE_NAMESPACE,
        _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
        _STALE_CHECK_CACHE_NAMESPACE,
        _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
        _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
        _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
        _USER_QUICK_STATS_CACHE_NAMESPACE,
        _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        _USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE,
        _CONFIDENCE_EXPLAINER_CACHE_NAMESPACE,
        _USER_OUTCOME_VELOCITY_CACHE_NAMESPACE,
        _USER_RUNS_PER_WEEK_CACHE_NAMESPACE,
        _USER_MOST_ACTIVE_WEEKDAY_CACHE_NAMESPACE,
        _USER_OLDEST_OPEN_ITEM_CACHE_NAMESPACE,
        _USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
        _USER_OUTCOME_RATE_CACHE_NAMESPACE,
        _USER_DECISION_TO_OUTCOME_DELAY_CACHE_NAMESPACE,
        _USER_INSIGHTS_CACHE_NAMESPACE,
        _USER_LAST_WEEK_STATS_CACHE_NAMESPACE,
        _USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE,
    ):
        cache_invalidate(namespace=namespace, user_id=user_id)


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
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a structured launch outcome, idempotently when keyed.

    Callers may supply ``client_request_id`` to make the submission safe to
    retry (e.g. after a network timeout): a repeat submission with the same
    key returns the originally recorded outcome with ``200`` instead of
    creating a duplicate row. Without a key the endpoint behaves exactly as
    before (always creates a row and returns ``201``).
    """
    project = get_owned_project(db, current_user.id, project_id)
    response.status_code = status.HTTP_201_CREATED

    existing = _existing_outcome_by_client_key(
        db,
        project_id,
        payload.client_request_id,
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _hydrate_record(existing)

    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    pred_conv, pred_mrr, sim_id = _prediction_columns(latest_sim)

    outcome = _build_outcome_row(
        project_id=project_id,
        payload=payload,
        pred_conv=pred_conv,
        pred_mrr=pred_mrr,
        sim_id=sim_id,
        client_request_id=payload.client_request_id,
    )
    db.add(outcome)

    project.status = "OUTCOME_RECORDED"
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same key won the unique-index race.
        # First write wins: roll back, return the winner as a 200 replay.
        db.rollback()
        existing = _existing_outcome_by_client_key(
            db,
            project_id,
            payload.client_request_id,
        )
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return _hydrate_record(existing)
    db.refresh(outcome)

    logger.info(
        "[Outcome] Recorded — project_id=%s actual_conv=%.3f pred_conv=%s calibration=%.1f",
        project_id,
        payload.actual_conversion_rate,
        pred_conv,
        outcome.calibration_score or 0.0,
    )
    _invalidate_outcome_caches(current_user.id)
    return _hydrate_record(outcome)


@router.post(
    "/{project_id}/outcomes/batch",
    response_model=OutcomeBatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record multiple launch outcomes in one transaction",
    # DB write — same per-actor cap as the single-outcome route.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def record_outcomes_batch(
    project_id: int,
    payload: OutcomeBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeBatchOut:
    """All-or-nothing backfill of structured launch outcomes.

    Each row may bind to an explicit completed simulation owned by this
    project; rows without a ``simulation_id`` fall back to the project's
    latest completed simulation (the same default as the single-record
    endpoint). Every row is validated before any write, rows are added in
    one ``add_all``, and the commit happens once — then the same cache
    surfaces as the single-record route are busted.
    """
    project = get_owned_project(db, current_user.id, project_id)

    requested_ids = sorted({
        item.simulation_id
        for item in payload.outcomes
        if item.simulation_id is not None
    })
    sim_by_id: dict[int, Simulation] = {}
    if requested_ids:
        sims = (
            db.query(Simulation)
            .filter(
                Simulation.id.in_(requested_ids),
                Simulation.project_id == project_id,
            )
            .all()
        )
        sim_by_id = {sim.id: sim for sim in sims}
        missing = [sim_id for sim_id in requested_ids if sim_id not in sim_by_id]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "simulation_ids not found for this project: "
                    f"{missing}"
                ),
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

    keys = [
        item.client_request_id
        for item in payload.outcomes
        if item.client_request_id is not None
    ]
    seen_keys: set[str] = set()
    for key in keys:
        if key in seen_keys:
            raise HTTPException(
                status_code=422,
                detail=f"duplicate client_request_id in batch: {key!r}",
            )
        seen_keys.add(key)

    existing_by_key = _existing_outcomes_by_client_key(
        db,
        project_id,
        set(keys),
    )
    rows, replayed = _resolve_batch_rows(
        project_id=project_id,
        items=payload.outcomes,
        sim_by_id=sim_by_id,
        latest_sim=latest_sim,
        existing_by_key=existing_by_key,
    )

    # A concurrent request can insert one of our keys between the pre-query
    # and the commit. The whole transaction rolls back, so re-resolve on
    # every race: conflicting keys become replays, the rest are retried.
    # The loop is bounded so pathological contention still surfaces as a
    # 500 instead of looping forever.
    for attempt in range(3):
        if not rows:
            # Every key already existed — pure replay, nothing new to persist.
            return _batch_replay_response(project_id, replayed)

        db.add_all(rows)
        project.status = "OUTCOME_RECORDED"
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise
            logger.warning(
                "[Outcome] Batch idempotency race on attempt %d — retrying",
                attempt + 1,
            )
            existing_by_key = _existing_outcomes_by_client_key(
                db,
                project_id,
                set(keys),
            )
            rows, replayed = _resolve_batch_rows(
                project_id=project_id,
                items=payload.outcomes,
                sim_by_id=sim_by_id,
                latest_sim=latest_sim,
                existing_by_key=existing_by_key,
            )
    for outcome in rows:
        db.refresh(outcome)

    # Echo records back in the caller's request order so clients can map
    # the response 1:1 onto their submitted rows (replays first-write-wins).
    outcome_records: list[OutcomeRecord] = []
    remaining_new = list(rows)
    for item in payload.outcomes:
        if (
            item.client_request_id is not None
            and item.client_request_id in existing_by_key
        ):
            outcome_records.append(
                _hydrate_record(existing_by_key[item.client_request_id])
            )
        else:
            outcome_records.append(_hydrate_record(remaining_new.pop(0)))

    logger.info(
        "[Outcome] Batch recorded — project_id=%s rows=%d",
        project_id,
        len(rows),
    )
    _invalidate_outcome_caches(current_user.id)
    return OutcomeBatchOut(
        project_id=project_id,
        created_count=len(rows),
        replayed_count=len(replayed),
        outcomes=outcome_records,
    )


@router.post(
    "/{project_id}/outcomes/batch/csv",
    response_model=OutcomeCsvImportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Backfill launch outcomes from a CSV file",
    # DB write — same per-actor cap as the JSON batch route.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def import_outcomes_csv(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutcomeCsvImportOut:
    """All-or-nothing CSV backfill of structured launch outcomes.

    The CSV uses the same columns as the JSON batch endpoint: the four
    required actual metrics plus optional ``days_since_launch``,
    ``actual_dau``, ``actual_nps``, ``notes``, ``client_request_id`` and
    ``simulation_id``. Rate columns accept spreadsheet percentages
    (``5%`` -> ``0.05``); read-only export columns are rejected with a
    clear error instead of being silently ignored.

    The file is validated row-by-row first; any problem rejects the whole
    import with a 422 and per-row errors, so a partially-fixed spreadsheet
    can never silently half-write. Clean rows are handed to the exact same
    batch recorder as ``POST /projects/{id}/outcomes/batch``, so
    idempotency keys, simulation binding, and cache invalidation behave
    identically.
    """
    get_owned_project(db, current_user.id, project_id)

    raw = file.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=400,
            detail="CSV file exceeds 1 MiB — split the file into smaller batches",
        )
    try:
        text_payload = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="CSV file must be UTF-8 encoded",
        )

    parsed = parse_outcomes_csv(text_payload)
    rejected_rows = len({error.row for error in parsed.errors})
    if parsed.errors:
        raise HTTPException(
            status_code=422,
            detail={
                "rows_scanned": parsed.data_row_count,
                "rows_rejected": rejected_rows,
                "errors": [
                    {"row": error.row, "column": error.column, "error": error.error}
                    for error in parsed.errors
                ],
            },
        )

    try:
        payload = OutcomeBatchCreate(
            outcomes=[OutcomeBatchItem(**row) for row in parsed.items]
        )
    except ValidationError as exc:
        errors = _csv_validation_errors(exc)
        raise HTTPException(
            status_code=422,
            detail={
                "rows_scanned": parsed.data_row_count,
                "rows_rejected": len({error["row"] for error in errors}),
                "errors": errors,
            },
        )

    batch = record_outcomes_batch(
        project_id=project_id,
        payload=payload,
        db=db,
        current_user=current_user,
    )
    return OutcomeCsvImportOut(
        project_id=batch.project_id,
        created_count=batch.created_count,
        replayed_count=batch.replayed_count,
        outcomes=batch.outcomes,
        rows_scanned=parsed.data_row_count,
        rows_rejected=0,
        errors=[],
    )


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
    "/{project_id}/outcome-gaps",
    response_model=ProjectOutcomeGapsOut,
    summary=(
        "Per-project outcome-feedback gaps digest — completed simulations "
        "that still need a real-world outcome"
    ),
    # Read-only scan over the project's simulations and founder_outcomes;
    # cap polling the same way the other per-project outcome digests do.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_project_outcome_gaps(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    learning_eligible_only: bool = Query(
        default=False,
        description=(
            "When true, only return unscored runs whose signal quality "
            "is at least 0.25 (the calibration learning-weight floor)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOutcomeGapsOut:
    """List completed simulations that still need founder outcome feedback.

    A completed run only teaches the calibration layer once the founder
    records a real-world outcome against it (``founder_outcomes``). This
    digest surfaces the gap at the item level — oldest first, with signal
    quality, predicted conversion, and an urgency tier — so the dashboard
    can turn "you only scored 40% of your runs" into a concrete list of
    which simulations to close out next.

    ``learning_eligible_only`` restricts both the list and the summary to
    runs whose signal quality meets the 0.25 learning-weight floor, which
    is the fastest path to better calibration. ``scored`` and
    ``total_completed`` always reflect the full project so the coverage
    rate stays honest under filtering.
    """
    get_owned_project(db, current_user.id, project_id)

    total_rows = (
        db.execute(
            text(
                """
                SELECT COUNT(*)::int AS total_completed
                FROM simulations s
                WHERE s.project_id = :pid
                  AND UPPER(s.status) = 'COMPLETED'
                """
            ),
            {"pid": project_id},
        )
        .mappings()
        .all()
    )
    total_completed = (
        int(total_rows[0]["total_completed"]) if total_rows else 0
    )

    scored_rows = (
        db.execute(
            text(
                """
                SELECT COUNT(DISTINCT fo.simulation_id)::int AS scored
                FROM founder_outcomes fo
                JOIN simulations s ON s.id = fo.simulation_id
                WHERE fo.project_id = :pid
                  AND s.project_id = :pid
                  AND UPPER(s.status) = 'COMPLETED'
                """
            ),
            {"pid": project_id},
        )
        .mappings()
        .all()
    )
    scored_count = int(scored_rows[0]["scored"]) if scored_rows else 0

    gap_counts_sql = """
        SELECT
            COUNT(*)::int AS unscored_total,
            COUNT(*) FILTER (
                WHERE COALESCE(s.signal_quality, 0) >= :min_sq
            )::int AS learning_eligible_unscored,
            MIN(s.created_at) AS oldest_unscored_created_at
        FROM simulations s
        WHERE s.project_id = :pid
          AND UPPER(s.status) = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1 FROM founder_outcomes fo
              WHERE fo.simulation_id = s.id
                AND fo.project_id = s.project_id
          )
    """
    gap_counts_params: dict[str, Any] = {"pid": project_id, "min_sq": 0.25}
    if learning_eligible_only:
        gap_counts_sql += "\n        AND COALESCE(s.signal_quality, 0) >= :min_sq"
    gap_rows = (
        db.execute(text(gap_counts_sql), gap_counts_params)
        .mappings()
        .all()
    )
    gap_row = gap_rows[0] if gap_rows else {}
    unscored_total = int(gap_row.get("unscored_total") or 0)
    learning_eligible_unscored = int(
        gap_row.get("learning_eligible_unscored") or 0
    )
    oldest_unscored_created_at = gap_row.get("oldest_unscored_created_at")

    items_sql = """
        SELECT
            s.id AS simulation_id,
            s.created_at AS created_at,
            s.signal_quality AS signal_quality,
            s.results_json AS results_json,
            (s.results_json IS NOT NULL) AS has_results
        FROM simulations s
        WHERE s.project_id = :pid
          AND UPPER(s.status) = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1 FROM founder_outcomes fo
              WHERE fo.simulation_id = s.id
                AND fo.project_id = s.project_id
          )
    """
    items_params: dict[str, Any] = {"pid": project_id, "limit": limit}
    if learning_eligible_only:
        items_sql += (
            "\n          AND COALESCE(s.signal_quality, 0) >= :min_sq"
        )
        items_params["min_sq"] = 0.25
    items_sql += (
        "\n        ORDER BY s.created_at ASC, s.id ASC\n        LIMIT :limit"
    )
    items_rows = (
        db.execute(text(items_sql), items_params).mappings().all()
    )

    payload = build_outcome_gaps_digest(
        project_id=project_id,
        rows=[dict(row) for row in items_rows],
        total_completed=total_completed,
        scored_count=scored_count,
        unscored_total=unscored_total,
        learning_eligible_unscored=learning_eligible_unscored,
        oldest_unscored_created_at=oldest_unscored_created_at,
        limit=limit,
        learning_eligible_only=learning_eligible_only,
        now=datetime.now(UTC),
    )
    return ProjectOutcomeGapsOut(**payload)


# Exports deliberately render every matching unscored run rather than a page,
# so a founder can keep the full feedback queue in a spreadsheet or pipeline.
# The cap is a defensive ceiling, not a user-facing pagination limit.
_OUTCOME_GAPS_EXPORT_ROW_CAP: int = 100_000


@router.get(
    "/{project_id}/outcome-gaps/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's outcome-feedback gaps digest as CSV, JSON, "
        "or Markdown"
    ),
    # Same bounded read cost as the JSON digest; cap polling like the
    # other per-project analytics exports.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_project_outcome_gaps(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the multi-section "
            "spreadsheet; ``json`` returns the raw gaps payload; ``md`` "
            "returns a founder-facing Markdown brief. Unsupported values "
            "return a 400 response."
        ),
    ),
    learning_eligible_only: bool = Query(
        default=False,
        description=(
            "When true, only export unscored runs whose signal quality "
            "is at least 0.25 (the calibration learning-weight floor)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export a project's outcome-feedback gaps digest for download.

    Reuses the same digest as ``GET /projects/{id}/outcome-gaps`` but
    renders every matching unscored simulation (not just the first page),
    so the exported queue is complete. Default ``format=csv`` renders a
    multi-section spreadsheet; ``json`` returns a strict machine-readable
    envelope; ``md`` returns a founder-facing brief.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected "
                "'csv', 'json', or 'md'"
            ),
        )

    payload = get_project_outcome_gaps(
        project_id=project_id,
        limit=_OUTCOME_GAPS_EXPORT_ROW_CAP,
        learning_eligible_only=learning_eligible_only,
        db=db,
        current_user=current_user,
    )
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": OUTCOME_GAPS_FORMAT_VERSION,
        "project_id": project_id,
    }

    if fmt == "json":
        body = outcome_gaps_to_json(payload, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="outcome-gaps-{project_id}.json"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    if fmt == "md":
        body = outcome_gaps_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="outcome-gaps-{project_id}.md"'
                ),
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    csv_text = outcome_gaps_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="outcome-gaps-{project_id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


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
    "/{project_id}/failure-attribution",
    response_model=FailureAttributionOut,
    summary=(
        "Group a project's recorded outcomes by the founder-reported "
        "primary failure reason"
    ),
    # Read-only aggregate over the calibration learning layer; bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_failure_attribution(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FailureAttributionOut:
    """Post-launch failure-attribution digest for one project.

    Groups ``founder_outcomes`` rows by ``primary_failure_reason`` and
    pairs each reason with the simulation's prediction error (in
    percentage points), data-confidence mix, and change flags. This is
    the first surface that turns the self-reported failure reason from a
    stored string into a founder-readable insight.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the founder_outcomes scan; the digest is
    # a dashboard tile and is re-polled within a short window. 120s TTL
    # matches the sibling outcomes-digest / funnel-calibration tiles.
    cached = cache_get_json(
        namespace=_FAILURE_ATTRIBUTION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return FailureAttributionOut(**cached)

    rows = _load_failure_attribution_rows(db, project_id)
    payload = build_failure_attribution(rows, project_id=project_id)
    cache_set_json(
        namespace=_FAILURE_ATTRIBUTION_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=120,
    )
    return FailureAttributionOut(**payload)


@router.get(
    "/{project_id}/failure-attribution/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's failure-attribution digest as CSV "
        "(or JSON with ?format=json)"
    ),
    # Same DB read cost as the JSON digest; cap polling so a dashboard
    # loop can't drive repeated scans of the learning layer.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_failure_attribution(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "digest payload. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download a project's failure-attribution digest.

    Delegates to the JSON endpoint (and shares its cache) so the exported
    numbers can never disagree with what the API returns.
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

    payload = get_failure_attribution(
        project_id=project_id,
        db=db,
        current_user=current_user,
    ).model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": FAILURE_ATTRIBUTION_FORMAT_VERSION,
    }

    if fmt == "json":
        body = failure_attribution_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="failure-attribution.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    body = failure_attribution_to_csv(payload, metadata=metadata).encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="failure-attribution.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )


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


@router.get(
    "/{project_id}/outcome-benchmark/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's real-world outcome peer benchmark as CSV "
        "(or JSON with ?format=json)"
    ),
    responses=_JSON_200,
    # Read-only aggregate over the calibration learning layer; bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_outcome_benchmark(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the raw "
            "benchmark payload. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download a real-world outcome benchmark in CSV (default) or JSON form.

    Delegates to the same ``get_outcome_benchmark`` builder as the JSON
    endpoint, so the exported comparison can never disagree with what the
    API returns. The CSV mirrors the project's current outcome, the peer
    distribution, the ranking verdict, and the founder-facing insights in
    one spreadsheet. Pure post-hoc analytics — no Celery, no LLM, no DB
    writes.
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

    benchmark = get_outcome_benchmark(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = benchmark.model_dump()
    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "category": payload.get("category"),
        "format_version": OUTCOME_BENCHMARK_FORMAT_VERSION,
    }

    if fmt == "json":
        text = outcome_benchmark_to_json(payload, metadata=metadata)
        body = text.encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="outcome-benchmark.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    csv_text = outcome_benchmark_to_csv(payload, metadata=metadata)
    body = csv_text.encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="outcome-benchmark.csv"'
            ),
            "Content-Length": str(len(body)),
        },
    )
