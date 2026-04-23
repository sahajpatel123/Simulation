from __future__ import annotations

import json
import logging
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.simulation.calibration import CalibrationEngine as PlatformCalibrationEngine
from app.simulation.calibration_engine import CalibrationEngine as LayerCalibrationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _predicted_from_results(results: dict) -> float:
    return float(
        results.get("mean_conversion_rate")
        or results.get("conversion_rate")
        or results.get("population_weighted_conversion")
        or 0.0
    )


def _require_admin(current_user: User) -> None:
    if getattr(current_user, "is_admin", False):
        return
    if settings.ADMIN_EMAILS:
        allowed = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
        if current_user.email and current_user.email.lower() in allowed:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _table_exists(db: Session, table_name: str) -> bool:
    r = db.execute(
        text(
            """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :name
        )
    """
        ),
        {"name": table_name},
    ).scalar()
    return bool(r)


def _cluster_param_table() -> str:
    return "cluster" + "_" + "parameters"


# ── existing platform endpoints ──


@router.get(
    "/",
    response_model=dict,
    summary="Platform-wide calibration accuracy metrics",
)
def get_platform_calibration(
    db: Session = Depends(get_db),
):
    engine = PlatformCalibrationEngine()
    metrics = engine.calculate_platform_accuracy(db)
    return {
        "platform_accuracy": metrics.platform_accuracy,
        "total_outcomes": metrics.total_outcomes,
        "total_projects_with_data": metrics.total_projects_with_data,
        "maturity_score": metrics.maturity_score,
        "calibration_trend": metrics.calibration_trend,
        "trend_delta": metrics.trend_delta,
        "data_sufficient": metrics.data_sufficient,
        "last_computed_at": metrics.last_computed_at,
        "category_accuracy": [asdict(category) for category in metrics.category_accuracy],
        "markov_adjustments": [asdict(adj) for adj in metrics.markov_adjustments],
        "sampling_adjustments": [asdict(adj) for adj in metrics.sampling_adjustments],
    }


@router.post(
    "/apply-adjustments",
    summary="Apply Markov prior adjustments from latest outcomes",
    responses=_JSON_200,
)
def apply_markov_adjustments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    engine = PlatformCalibrationEngine()
    metrics = engine.update_markov_priors(db)
    return {
        "applied": len(metrics.markov_adjustments),
        "platform_accuracy": metrics.platform_accuracy,
        "data_sufficient": metrics.data_sufficient,
        "adjustments_made": [
            {
                "transition": f"{adj.from_state} → {adj.to_state}",
                "delta": adj.delta,
                "rationale": adj.rationale,
            }
            for adj in metrics.markov_adjustments
        ],
    }


# ── founder outcome (learning layer) ──


@router.post(
    "/outcome",
    summary="Founder submits post-launch outcome (optional learning path)",
    responses=_JSON_200,
)
def submit_outcome(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim_id = body.get("simulation_id")
    if sim_id is None:
        raise HTTPException(status_code=400, detail="simulation_id is required")
    try:
        actual_cr = float(body.get("actual_conversion_rate", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="actual_conversion_rate must be a number") from None
    launched = bool(body.get("launched", True))
    notes = str(body.get("notes", ""))[:500] if body.get("notes") is not None else ""

    sim: Simulation | None = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(
            Simulation.id == int(sim_id),
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")

    results: dict
    rj = sim.results_json
    if isinstance(rj, dict):
        results = rj
    else:
        results = json.loads(rj or "{}")

    predicted_cr = _predicted_from_results(results)
    gap = round(abs(actual_cr - predicted_cr), 4)
    signal_quality = float(sim.signal_quality or 0.0)

    # Upsert founder_outcomes (required for learn step)
    row = db.execute(
        text("SELECT id FROM founder_outcomes WHERE simulation_id = :sid"),
        {"sid": int(sim_id)},
    ).fetchone()

    if row:
        db.execute(
            text(
                """
            UPDATE founder_outcomes
            SET project_id = :pid,
                days_since_launch = :days,
                actual_conversion_rate = :acr,
                data_confidence = 'ESTIMATED',
                product_changed_since_sim = FALSE,
                user_id = COALESCE(user_id, :uid),
                signal_quality_at_run = :sq,
                launched = :launched,
                notes = :notes
            WHERE simulation_id = :sid
            """
            ),
            {
                "pid": sim.project_id,
                "days": int(body.get("days_since_launch", 30)),
                "acr": actual_cr,
                "sq": signal_quality,
                "uid": current_user.id,
                "launched": launched,
                "notes": notes,
                "sid": int(sim_id),
            },
        )
    else:
        db.execute(
            text(
                """
            INSERT INTO founder_outcomes
            (simulation_id, project_id, days_since_launch, actual_conversion_rate,
             data_confidence, product_changed_since_sim, user_id, signal_quality_at_run,
             launched, notes, created_at)
            VALUES (:sid, :pid, :days, :acr, 'ESTIMATED', FALSE, :uid, :sq, :launched, :notes, NOW())
            """
            ),
            {
                "sid": int(sim_id),
                "pid": sim.project_id,
                "days": int(body.get("days_since_launch", 30)),
                "acr": actual_cr,
                "uid": current_user.id,
                "sq": signal_quality,
                "launched": launched,
                "notes": notes,
            },
        )
    db.commit()

    fo_row = db.execute(
        text("SELECT * FROM founder_outcomes WHERE simulation_id = :sid ORDER BY id DESC LIMIT 1"),
        {"sid": int(sim_id)},
    ).mappings().first()
    if not fo_row:
        raise HTTPException(status_code=500, detail="Failed to persist outcome")

    fo = SimpleNamespace(
        id=fo_row["id"],
        actual_conversion_rate=float(fo_row["actual_conversion_rate"]),
        product_changed_since_sim=bool(fo_row.get("product_changed_since_sim")),
        data_confidence=fo_row.get("data_confidence") or "ESTIMATED",
    )

    eng = LayerCalibrationEngine()
    try:
        will_learn = bool(eng.validate_outcome(fo, sim, db))
    except Exception as exc:  # noqa: BLE001
        logger.warning("validate_outcome failed: %s", exc)
        will_learn = False

    fo2 = db.execute(
        text("SELECT * FROM founder_outcomes WHERE id = :id"),
        {"id": fo_row["id"]},
    ).mappings().first()
    if not fo2:
        raise HTTPException(status_code=500, detail="Outcome row missing after validation")

    out_proxy = SimpleNamespace(
        id=fo2["id"],
        actual_conversion_rate=float(fo2["actual_conversion_rate"]),
        product_changed_since_sim=bool(fo2.get("product_changed_since_sim")),
        data_confidence=fo2.get("data_confidence") or "ESTIMATED",
        validated=bool(fo2.get("validated", False)),
        learning_weight=float(fo2.get("learning_weight") or 0.0),
    )

    launched_count = db.execute(
        text(
            """
        SELECT COUNT(*)::int
        FROM founder_outcomes fo
        JOIN projects p ON p.id = fo.project_id
        WHERE p.user_id = :uid AND COALESCE(fo.launched, FALSE) = TRUE
    """
        ),
        {"uid": current_user.id},
    ).scalar()
    launched_count = int(launched_count or 0)

    calibration_written = False
    if (
        signal_quality >= 0.25
        and launched_count >= 3
        and out_proxy.validated
        and out_proxy.learning_weight > 0.0
    ):
        try:
            eng.update_user_accuracy_profile(current_user.id, out_proxy, sim, db)
            calibration_written = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("update_user_accuracy_profile failed: %s", exc)

    if not calibration_written:
        exists = db.execute(
            text(
                """
            SELECT 1 FROM user_simulation_accuracy_history
            WHERE user_id = :uid AND simulation_id = :sid
            """
            ),
            {"uid": current_user.id, "sid": int(sim_id)},
        ).fetchone()
        if not exists:
            try:
                db.execute(
                    text(
                        """
                    INSERT INTO user_simulation_accuracy_history
                    (user_id, simulation_id, predicted_conversion, actual_conversion,
                     absolute_gap, signal_quality_at_run, accuracy_trend, created_at)
                    VALUES (:uid, :sid, :pred, :act, :gap, :sq, 'INSUFFICIENT_DATA', NOW())
                    """
                    ),
                    {
                        "uid": current_user.id,
                        "sid": int(sim_id),
                        "pred": predicted_cr,
                        "act": actual_cr,
                        "gap": abs(actual_cr - predicted_cr),
                        "sq": signal_quality,
                    },
                )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("optional history insert failed: %s", exc)
                db.rollback()

    message = (
        "Thank you. The model has updated based on your data."
        if calibration_written
        else "Outcome recorded. The model improves as more founders return with data."
    )

    return {
        "gap": round(gap, 4),
        "predicted": round(predicted_cr, 4),
        "actual": actual_cr,
        "outcomes_submitted": launched_count,
        "message": message,
    }


@router.get(
    "/my-accuracy",
    summary="User-facing accuracy report (history, blindspots, biases)",
    responses=_JSON_200,
)
def get_my_accuracy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        text(
            """
        SELECT simulation_id, predicted_conversion, actual_conversion, absolute_gap, created_at
        FROM user_simulation_accuracy_history
        WHERE user_id = :uid
        ORDER BY created_at ASC
    """
        ),
        {"uid": current_user.id},
    ).fetchall()

    if not rows:
        return {
            "has_data": False,
            "message": "Run a simulation and return with real data to see your accuracy trend.",
            "history": [],
            "mean_gap": None,
            "trend": None,
            "blindspots": [],
            "biases": [],
        }

    history: list[dict] = []
    for r in rows:
        g = r.absolute_gap
        history.append(
            {
                "simulation_id": r.simulation_id,
                "predicted": round(float(r.predicted_conversion), 4) if r.predicted_conversion is not None else 0.0,
                "actual": round(float(r.actual_conversion or 0), 4) if r.actual_conversion is not None else 0.0,
                "gap": round(float(g), 4) if g is not None else 0.0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )

    gaps = [h["gap"] for h in history if h.get("gap") is not None]
    mean_gap = round(sum(gaps) / len(gaps), 4) if gaps else None

    trend: str | None = None
    if len(gaps) >= 3:
        recent = gaps[-3:]
        trend = (
            "IMPROVING" if recent[-1] < recent[0] else "STABLE" if abs(recent[-1] - recent[0]) < 0.02 else "WIDENING"
        )

    blindspot_rows = db.execute(
        text(
            """
        SELECT blindspot_type, blindspot_value, occurrence_count
        FROM user_market_blindspots
        WHERE user_id = :uid
        ORDER BY occurrence_count DESC
        LIMIT 5
    """
        ),
        {"uid": current_user.id},
    ).fetchall()

    blindspots = [
        {
            "type": r.blindspot_type,
            "value": r.blindspot_value,
            "occurrence_count": r.occurrence_count,
        }
        for r in blindspot_rows
    ]

    bias_rows = db.execute(
        text(
            """
        SELECT architect_name, ema_delta, reliability_score
        FROM user_claim_accuracy_profiles
        WHERE user_id = :uid AND reliability_score >= 0.40
        ORDER BY reliability_score DESC
        LIMIT 5
    """
        ),
        {"uid": current_user.id},
    ).fetchall()

    biases: list[dict] = []
    for r in bias_rows:
        ema = float(r.ema_delta or 0.0)
        direction = "over-claims" if ema > 0 else "under-claims" if ema < 0 else "neutral"
        name = (r.architect_name or "Architect").replace("Architect", "").strip() or (r.architect_name or "Architect")
        biases.append(
            {
                "architect": name,
                "direction": direction,
                "reliability": round(float(r.reliability_score or 0.0), 3),
            }
        )

    return {
        "has_data": True,
        "history": history,
        "mean_gap": mean_gap,
        "trend": trend,
        "blindspots": blindspots,
        "biases": biases,
        "message": "The model gets more accurate every time you return with real data.",
    }


@router.get(
    "/admin/status",
    summary="Admin-only calibration and sample counts",
    responses=_JSON_200,
)
def admin_calibration_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    counts = db.execute(
        text(
            """
        SELECT
            results_json->>'product_type_detected' AS product_type_detected,
            COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE UPPER(TRIM(status)) = 'COMPLETED' AND COALESCE(signal_quality, 0) >= 0.5)::int AS high_quality
        FROM simulations
        WHERE UPPER(TRIM(status)) = 'COMPLETED'
        GROUP BY 1
        """
        )
    ).fetchall()

    product_type_counts = [dict(r._mapping) for r in counts] if counts else []

    if _table_exists(db, _cluster_param_table()):
        eff_rows = db.execute(
            text(
                f"""
            SELECT cluster_id, trait_name, effective_sample_count
            FROM {_cluster_param_table()}
            WHERE effective_sample_count >= 15
            ORDER BY effective_sample_count DESC
            LIMIT 200
            """
            )
        ).fetchall()
        effective_samples = [dict(r._mapping) for r in eff_rows] if eff_rows else []
    else:
        effective_samples = []

    quarantine = db.execute(
        text(
            """
        SELECT s.id, s.project_id, s.signal_quality, s.created_at
        FROM simulations s
        WHERE UPPER(TRIM(s.status)) = 'COMPLETED'
          AND COALESCE(s.signal_quality, 0) < 0.25
        ORDER BY s.created_at DESC
        LIMIT 20
        """
        )
    ).fetchall()
    quarantine_queue = [dict(r._mapping) for r in quarantine]

    return {
        "product_type_counts": product_type_counts,
        "effective_samples": effective_samples,
        "quarantine_queue": quarantine_queue,
        "quarantine_count": len(quarantine_queue),
    }
