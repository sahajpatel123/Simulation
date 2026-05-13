import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.claude_client import claude_call_with_fallback
from app.core.intake_processor import adjust_assumption_confidence, build_enriched_description
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.sanitiser import sanitise_assumption, sanitise_description, sanitise_text
from app.core.prompts import (
    ASSUMPTION_EXTRACTION_PROMPT,
    COMPETITIVE_ANALYSIS_PROMPT,
    INTERVENTION_PROMPT,
    PREMORTEM_PROMPT,
    PROTOTYPE_GENERATION_PROMPT,
    build_simulation_summary,
)
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.prototype import Prototype
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.assumption import (
    AssumptionExtractRequest,
    AssumptionListResponse,
    AssumptionOut,
)
from app.schemas.competitive import (
    CompetitiveAnalysisOut,
    CompetitiveAnalysisRequest,
    Competitor,
    GapAnalysis,
    MarketMap,
    VALID_POSITIONS,
)
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentSummary,
    ManualParams,
    SCENARIO_PRESETS,
)
from app.schemas.intervention import Intervention, InterventionOut, InterventionRequest
from app.schemas.premortem import FailureMode, PremortemOut, PremortemRequest
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectOut, ProjectPatch
from app.schemas.prototype import FunnelEdge, FunnelGraph, FunnelNode, PrototypeOut
from app.schemas.stress_test import (
    AssumptionStressResult,
    StressTestOut,
    StressTestStatusOut,
)
from app.simulation.calibration_engine import CalibrationEngine
from app.api.v1.common import get_owned_project
from app.core.utils import extract_json_from_markdown
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.competitive_software import CompetitiveSoftwareAnalyser
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.simulation.scored_assumption import score_assumptions, signal_quality_tier
from app.tasks.simulation_tasks import run_full_simulation
from app.tasks.stress_test_tasks import run_assumption_stress_test

router = APIRouter(prefix="/projects", tags=["projects"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

_comp_software_analyser = CompetitiveSoftwareAnalyser()
_conductor = Conductor()

_SOFTWARE_PRODUCT_TYPES: frozenset[ProductType] = frozenset(
    {
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
        ProductType.ENTERPRISE_SOFTWARE,
    }
)


def _product_type_enum_from_results(raw: str | None) -> ProductType:
    s = (raw or "saas").strip().lower()
    for e in ProductType:
        if e.value == s:
            return e
    return ProductType.SAAS


def _software_benchmark_key(pt: ProductType) -> str:
    return pt.value if pt in _SOFTWARE_PRODUCT_TYPES else "saas"


def _title_fingerprint(title: str) -> str:
    """Normalised dossier title used to detect rename vs last précis mint."""
    return (title or "").strip()[:500]


def _backfill_display_precis_lazy(db: Session, project: Project) -> None:
    """One-time mint of display précis for legacy rows (fingerprint unset)."""
    if project.precis_title_fingerprint is not None:
        return
    try:
        from app.services.dossier_intelligence import generate_precis

        line = generate_precis(project.title, project.description)
        if line:
            project.precis = line
        project.precis_title_fingerprint = _title_fingerprint(project.title)
        db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


# ── THE BRIEF — founder-authored product spec ────────────────────────────


@router.get(
    "/{project_id}/brief",
    summary="Get the current brief for a dossier",
)
def get_brief(
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
    import json as _json

    features = []
    if project.brief_features_json:
        try:
            features = _json.loads(project.brief_features_json)
        except Exception:
            features = []
    return {
        "positioning": project.brief_positioning or "",
        "features": features,
        "hook": project.brief_hook or "",
        "completed_at": (
            project.brief_completed_at.isoformat() if project.brief_completed_at else None
        ),
    }


@router.put(
    "/{project_id}/brief",
    summary="Save brief fields for a dossier",
)
def save_brief(
    project_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json as _json

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    positioning = (payload.get("positioning") or "").strip()
    features = payload.get("features") or []
    hook = (payload.get("hook") or "").strip()
    mark_complete = bool(payload.get("mark_complete", False))

    if positioning is not None:
        project.brief_positioning = positioning
    if isinstance(features, list):
        project.brief_features_json = _json.dumps([str(f).strip() for f in features if str(f).strip()][:5])
    if hook is not None:
        project.brief_hook = hook

    if mark_complete and positioning and hook:
        project.brief_completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(project)

    features_out = []
    if project.brief_features_json:
        try:
            features_out = _json.loads(project.brief_features_json)
        except Exception:
            features_out = []

    return {
        "positioning": project.brief_positioning or "",
        "features": features_out,
        "hook": project.brief_hook or "",
        "completed_at": (
            project.brief_completed_at.isoformat() if project.brief_completed_at else None
        ),
    }


@router.post(
    "/{project_id}/brief/assist",
    summary="Get editorial assistance for a brief field",
)
def assist_brief(
    project_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.brief_assistance import assist

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = payload.get("mode")
    field = payload.get("field")
    current_value = payload.get("current_value", "")

    if mode not in ("refine", "suggest", "critique"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if field not in ("positioning", "features", "hook"):
        raise HTTPException(status_code=400, detail="Invalid field")

    result = assist(
        mode=mode,
        field=field,
        dossier_title=project.title,
        dossier_description=project.description,
        current_value=current_value,
    )

    if not result:
        raise HTTPException(status_code=500, detail="Assistance generation failed")

    return result


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List the current user’s projects",
)
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return ProjectListResponse(
        projects=[ProjectOut.model_validate(p) for p in projects],
        total=len(projects),
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update dossier title or description",
)
def patch_project(
    project_id: int,
    payload: ProjectPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.title is None and payload.description is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide title and/or description to update",
        )
    project = get_owned_project(db, current_user.id, project_id)

    title_changed = False
    if payload.title is not None:
        new_title = sanitise_text(payload.title.strip(), max_length=500)
        if not new_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Title cannot be empty",
            )
        if new_title != project.title:
            project.title = new_title
            title_changed = True

    if payload.description is not None:
        project.description = sanitise_description(payload.description)

    if title_changed:
        try:
            from app.services.dossier_intelligence import generate_precis

            line = generate_precis(project.title, project.description)
            if line:
                project.precis = line
        except Exception as exc:
            logger.warning("precis refresh on dossier rename failed: %s", exc)
        project.precis_title_fingerprint = _title_fingerprint(project.title)

    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.patch(
    "/{project_id}/archive",
    response_model=ProjectOut,
    summary="Move dossier to the archive",
)
def archive_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    project.is_archived = True
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.patch(
    "/{project_id}/unarchive",
    response_model=ProjectOut,
    summary="Restore dossier from the archive",
)
def unarchive_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    project.is_archived = False
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get(
    "/{project_id}/clusters",
    summary="Cluster-level conversion from the latest completed simulation",
    responses=_JSON_200,
)
def get_project_clusters(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not latest_sim or not latest_sim.results_json:
        return {"clusters": [], "message": "No completed simulation found"}

    breakdown = latest_sim.results_json.get("cluster_breakdown", {})
    _clusters = {c.cluster_id: c for c in ClusterRegistry().all_clusters()}
    clusters_out = [
        {
            "cluster_id": cid,
            "name": _clusters[cid].name if cid in _clusters else cid,
            "conversion_rate": round(float(cr), 4),
            "population_fraction": round(_clusters[cid].population_weight, 4)
            if cid in _clusters
            else 0.0,
            "dominant_behavior": _clusters[cid].dominant_behavior_pattern
            if cid in _clusters
            else "",
            "known_failure_modes": _clusters[cid].known_failure_modes if cid in _clusters else [],
            "demographic_profile": _clusters[cid].demographic_profile if cid in _clusters else {},
        }
        for cid, cr in sorted(breakdown.items(), key=lambda x: -x[1])
    ]
    return {"clusters": clusters_out, "simulation_id": latest_sim.id}


@router.get(
    "/{project_id}/domain-findings",
    summary="Architect domain findings from the latest completed run",
    responses=_JSON_200,
)
def get_domain_findings(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not latest_sim or not latest_sim.results_json:
        return {"findings": [], "message": "No completed simulation found"}

    results = latest_sim.results_json
    return {
        "findings": results.get("domain_findings", []),
        "primary_failure_domain": results.get("primary_failure_domain", "unknown"),
        "highest_value_cluster": results.get("highest_value_cluster", {}),
        "cluster_narrative": results.get("cluster_narrative", ""),
        "simulation_id": latest_sim.id,
    }


@router.post(
    "/{project_id}/outcome-feedback",
    summary="Record lightweight outcome feedback and calibration (projects router)",
    responses=_JSON_200,
)
def submit_outcome_feedback(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    simulation_id = body.get("simulation_id")
    actual_cr = body.get("actual_conversion_rate")
    if not simulation_id or actual_cr is None:
        raise HTTPException(
            status_code=400,
            detail="simulation_id and actual_conversion_rate required",
        )

    project = get_owned_project(db, current_user.id, project_id)

    sim = db.query(Simulation).filter(Simulation.id == simulation_id).first()
    if not sim or sim.project_id != project_id:
        raise HTTPException(status_code=404, detail="Simulation not found")

    results = sim.results_json or {}
    predicted = float(
        results.get("mean_conversion_rate")
        or results.get("conversion_rate")
        or results.get("population_weighted_conversion")
        or 0
    )
    actual_cr = float(actual_cr)

    if predicted > 0.10 and actual_cr > predicted * 3.0:
        return {
            "error": "Outcome outside plausible range — actual is 3x+ predicted. Please verify numbers.",
            "code": "IMPLAUSIBLE_HIGH",
        }

    if predicted > 0.10 and actual_cr <= predicted * 0.10:
        return {
            "error": "Outcome outside plausible range — actual is 90%+ below predicted. Please verify numbers.",
            "code": "IMPLAUSIBLE_LOW",
        }

    eng = CalibrationEngine()
    db.execute(
        text("""
        INSERT INTO founder_outcomes
        (simulation_id, project_id, days_since_launch, actual_conversion_rate,
         actual_drop_at_browse_pct, actual_drop_at_consider_pct, actual_drop_at_decide_pct,
         primary_failure_reason, product_changed_since_sim, pricing_changed,
         target_market_changed, data_confidence, signal_quality_at_run, created_at)
        VALUES (:sid,:pid,:days,:acr,:br,:cr,:dr,:pfr,:pc,:pricing,:tm,:dc,:sq,NOW())
    """),
        {
            "sid": simulation_id,
            "pid": project_id,
            "days": body.get("days_since_launch", 90),
            "acr": actual_cr,
            "br": body.get("actual_drop_at_browse_pct"),
            "cr": body.get("actual_drop_at_consider_pct"),
            "dr": body.get("actual_drop_at_decide_pct"),
            "pfr": body.get("primary_failure_reason"),
            "pc": body.get("product_changed_since_sim", False),
            "pricing": body.get("pricing_changed", False),
            "tm": body.get("target_market_changed", False),
            "dc": body.get("data_confidence", "ESTIMATED"),
            "sq": float(sim.signal_quality or 0.0),
        },
    )
    db.commit()

    outcome_row = db.execute(
        text("SELECT * FROM founder_outcomes WHERE simulation_id=:sid ORDER BY id DESC LIMIT 1"),
        {"sid": simulation_id},
    ).fetchone()

    if not outcome_row:
        raise HTTPException(status_code=500, detail="Failed to load inserted outcome")

    class _OutcomeProxy:
        def __init__(self, r) -> None:
            self.id = r.id
            self.actual_conversion_rate = r.actual_conversion_rate
            self.product_changed_since_sim = r.product_changed_since_sim
            self.data_confidence = r.data_confidence
            self.learning_weight = getattr(r, "learning_weight", None)
            self.validated = getattr(r, "validated", True)

    outcome = _OutcomeProxy(outcome_row)
    will_learn = eng.validate_outcome(outcome, sim, db)
    fresh = db.execute(
        text("SELECT learning_weight, validated FROM founder_outcomes WHERE id=:id"),
        {"id": outcome.id},
    ).fetchone()
    if fresh:
        outcome.learning_weight = fresh.learning_weight
        outcome.validated = fresh.validated
    learning_weight_val = (
        float(fresh.learning_weight) if fresh and fresh.learning_weight is not None else 0.0
    )

    eng.update_user_accuracy_profile(current_user.id, outcome, sim, db)

    trend_row = db.execute(
        text("""
        SELECT accuracy_trend FROM user_simulation_accuracy_history
        WHERE user_id=:uid ORDER BY created_at DESC LIMIT 1
    """),
        {"uid": current_user.id},
    ).fetchone()

    return {
        "stored": True,
        "will_improve_model": will_learn,
        "learning_weight": round(learning_weight_val, 4),
        "signal_quality": float(sim.signal_quality or 0.0),
        "accuracy_trend": trend_row.accuracy_trend if trend_row else "INSUFFICIENT_DATA",
        "message": (
            "Thank you — your outcome data improves TheCee for all founders."
            if will_learn
            else "Stored but not used for calibration (signal quality too low or product changed)."
        ),
    }


@router.get(
    "/{project_id}/assumptions",
    response_model=AssumptionListResponse,
    summary="List scored assumptions for a project",
)
def get_assumptions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )
    hidden_count = sum(1 for a in assumptions if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in assumptions],
        total=len(assumptions),
        hidden_count=hidden_count,
    )


@router.post(
    "/{project_id}/extract-assumptions",
    response_model=AssumptionListResponse,
    summary="Run Claude to extract and score assumptions",
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def extract_assumptions(
    project_id: int,
    payload: AssumptionExtractRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    raw_description = (
        payload.description
        if payload and payload.description
        else project.description
    )
    description = sanitise_description(raw_description or "")

    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Description too short to extract meaningful assumptions",
        )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": ASSUMPTION_EXTRACTION_PROMPT.format(
                        description=description
                    ),
                }
            ],
            system=(
                "You are a world-class startup mentor specializing in surfacing "
                "dangerous hidden assumptions that kill products. "
                "You ALWAYS return valid JSON only, no markdown, no explanation."
            ),
            model="claude-sonnet-4-5",
            max_tokens=2000,
            fallback_key="assumption_extraction",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()

        raw = extract_json_from_markdown(raw)
        parsed = json.loads(raw)
        assumptions_data = parsed.get("assumptions", [])

        if not isinstance(assumptions_data, list):
            raise ValueError("Claude returned unexpected format")

        prepped: list[dict] = []
        for item in assumptions_data:
            if not isinstance(item, dict):
                continue
            t = str(item.get("text", "")).strip()
            prepped.append(
                {
                    **item,
                    "text": t,
                    "assumption": t,
                    "claim_confidence": str(item.get("claim_confidence", "DESIGN_INTENT")),
                }
            )
        assumptions_data = adjust_assumption_confidence(
            prepped, project.intake_mode or "IDEA"
        )
        for a in assumptions_data:
            t = sanitise_assumption(str(a.get("text", a.get("assumption", ""))))
            a["text"] = t
            a["assumption"] = t

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned invalid JSON — retry the request",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Assumption extraction failed: {str(e)}",
        )

    db.query(Assumption).filter(Assumption.project_id == project_id).delete()
    db.commit()

    saved = []
    for item in assumptions_data:
        sensitivity = str(item.get("sensitivity", "MEDIUM")).upper()
        if sensitivity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            sensitivity = "MEDIUM"

        assumption = Assumption(
            project_id=project_id,
            text=str(item.get("text", "")).strip(),
            category=str(item.get("category", "Market")).strip(),
            sensitivity=sensitivity,
            impact_score=min(10.0, max(1.0, float(item.get("impact_score", 5.0)))),
            is_hidden=bool(item.get("is_hidden", False)),
        )
        db.add(assumption)
        saved.append(assumption)

    project.status = "ASSUMPTIONS_EXTRACTED"
    db.commit()

    for assumption in saved:
        db.refresh(assumption)

    # Score assumptions and compute signal quality for this extraction run.
    scored_list, hard_count, soft_flags, sq = score_assumptions(
        [
            {
                "id": a.id,
                "text": a.text,
                "category": a.category,
                "impact_score": a.impact_score,
                "claim_confidence": item.get("claim_confidence"),
            }
            for a, item in zip(saved, assumptions_data, strict=True)
        ]
    )

    # Build confidence distribution summary (count per tier).
    confidence_dist: dict[str, int] = {}
    for sa in scored_list:
        key = sa.claim_confidence.value
        confidence_dist[key] = confidence_dist.get(key, 0) + 1

    sq_tier = signal_quality_tier(sq)

    # Persist signal_quality on the most recent simulation for this project,
    # or update it when the next simulation is created (Step 37 task picks this up).
    # For now, write to the latest QUEUED/RUNNING simulation if one exists.
    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if latest_sim is not None:
        latest_sim.signal_quality = sq
        latest_sim.claim_confidence_distribution = confidence_dist
        db.commit()

    # Apply personal accuracy adjustment from user_claim_accuracy_profiles
    # if the user has enough history (sample_count >= 3, reliability >= 0.40).
    # This is a read-only advisory enrichment — it does not modify saved rows.
    user_reliability_note: str | None = None
    try:
        profile_rows = db.execute(
            text(
                "SELECT architect_name, ema_delta, reliability_score, sample_count "
                "FROM user_claim_accuracy_profiles "
                "WHERE user_id = :uid AND sample_count >= 3 AND reliability_score >= 0.40"
            ),
            {"uid": current_user.id},
        ).fetchall()
        if profile_rows:
            user_reliability_note = (
                f"Personal accuracy profile active: {len(profile_rows)} architects calibrated."
            )
    except Exception as _exc:
        logger.debug(
            "%s suppressed: %s",
            __name__,
            _exc,
        )

    hidden_count = sum(1 for a in saved if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in saved],
        total=len(saved),
        hidden_count=hidden_count,
        signal_quality=sq,
        signal_quality_tier=sq_tier,
        claim_confidence_distribution=confidence_dist,
        soft_contradiction_flags=soft_flags,
        message=(
            user_reliability_note or "Assumptions extracted successfully"
        ),
    )


@router.post(
    "/{project_id}/generate-prototype",
    response_model=PrototypeOut,
    summary="Generate a landing-page HTML prototype (Claude)",
)
def generate_prototype(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    if not project.description or len(project.description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description is too short to generate a prototype",
        )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": PROTOTYPE_GENERATION_PROMPT.format(
                        description=project.description
                    ),
                }
            ],
            system=(
                "You are a world-class product designer and conversion rate expert. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Your HTML prototypes look like real funded startup products."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            fallback_key="prototype_generation",
            timeout=120,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()

        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))

        html_content = parsed.get("html_content", "")
        funnel_data = parsed.get("funnel_graph", {})

        if not html_content or len(html_content) < 100:
            raise ValueError("Generated HTML is too short or empty")

        if not funnel_data.get("nodes") or not funnel_data.get("edges"):
            raise ValueError("Funnel graph is missing nodes or edges")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — please retry",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Prototype generation failed: {str(e)}",
        )

    existing = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )

    if existing:
        existing.html_content = html_content
        existing.funnel_graph_json = json.dumps(funnel_data)
        prototype = existing
    else:
        prototype = Prototype(
            project_id=project_id,
            html_content=html_content,
            funnel_graph_json=json.dumps(funnel_data),
        )
        db.add(prototype)

    project.status = "PROTOTYPE_GENERATED"
    project.prototype_html = html_content
    project.funnel_graph_json = json.dumps(funnel_data)

    db.commit()
    db.refresh(prototype)

    try:
        funnel_graph = FunnelGraph(
            nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
            edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
        )
    except Exception:
        funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=html_content,
        funnel_graph=funnel_graph,
    )


@router.get(
    "/{project_id}/prototype",
    response_model=PrototypeOut,
    summary="Get stored HTML prototype and funnel graph",
)
def get_prototype(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    prototype = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )
    if not prototype:
        raise HTTPException(
            status_code=404,
            detail="No prototype generated yet — call POST /generate-prototype first",
        )

    funnel_graph = None
    if prototype.funnel_graph_json:
        try:
            funnel_data = json.loads(prototype.funnel_graph_json)
            funnel_graph = FunnelGraph(
                nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
                edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
            )
        except Exception:
            funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=prototype.html_content,
        funnel_graph=funnel_graph,
    )


@router.post(
    "/{project_id}/premortem",
    response_model=PremortemOut,
    summary="Run premortem failure mode analysis (Claude)",
)
def run_premortem(
    project_id: int,
    payload: PremortemRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short for pre-mortem analysis",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
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

    assumptions_text = "\n".join(
        f"- [{a.sensitivity}] {a.text} (impact: {a.impact_score}/10)" for a in assumptions
    ) or "No assumptions extracted yet."

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    domain_findings_text = (
        "\n".join(
            [
                f"[{f.get('severity', 'INFO')}] {f.get('architect_name', '')} / "
                f"{f.get('cluster_name', '')}: {f.get('finding', '')} "
                f"(impact: {float(f.get('conversion_impact', 0) or 0):.3f})"
                for f in findings[:10]
            ]
        )
        if findings
        else "No domain findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": PREMORTEM_PROMPT.format(
                        domain_findings_text=domain_findings_text,
                        primary_failure_domain=primary_fd,
                        highest_value_cluster=hv_name,
                        cluster_narrative=narrative,
                    ),
                }
            ],
            system=(
                "You are an elite startup failure analyst specialising in pre-mortem analysis. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=2800,
            fallback_key="premortem",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))
        raw_modes = parsed.get("failure_modes", [])

        if not isinstance(raw_modes, list) or len(raw_modes) == 0:
            raise ValueError("Claude returned empty failure_modes list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON - retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Pre-mortem analysis failed: {str(exc)}",
        )

    failure_modes: list[FailureMode] = []
    for item in raw_modes:
        try:
            fm = FailureMode(
                title=str(item.get("title", item.get("failure_mode", "Unknown failure"))).strip(),
                probability=float(item.get("probability", 0.5)),
                severity=str(item.get("severity", "MEDIUM")),
                trigger_condition=str(item.get("trigger_condition", "")).strip(),
                linked_assumption_texts=[
                    str(a).strip()
                    for a in item.get(
                        "linked_assumption_texts", item.get("linked_assumptions", [])
                    )
                ],
                intervention=str(
                    item.get("intervention", item.get("recommended_intervention", ""))
                ).strip(),
                intervention_impact=str(
                    item.get("intervention_impact", item.get("expected_impact", ""))
                ).strip(),
                earliest_signal=str(item.get("earliest_signal", "")).strip(),
            )
            failure_modes.append(fm)
        except Exception:
            continue

    if not failure_modes:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid failure modes from Claude response",
        )

    failure_modes.sort(key=lambda f: f.probability, reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    premortem_data = {
        "failure_modes": [fm.model_dump() for fm in failure_modes],
        "generated_at": now,
        "simulation_id": latest_sim.id if latest_sim else None,
        "assumptions_count": len(assumptions),
    }

    project.premortem_json = premortem_data
    project.status = "PREMORTEM_COMPLETE"
    db.commit()

    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=now,
    )


@router.get(
    "/{project_id}/premortem",
    response_model=PremortemOut,
    summary="Get stored premortem JSON",
)
def get_premortem(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "premortem_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No pre-mortem generated yet - call POST /premortem first",
        )

    failure_modes = [FailureMode(**fm) for fm in data.get("failure_modes", [])]
    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=data.get("generated_at", ""),
    )


@router.post(
    "/{project_id}/stress-test",
    response_model=StressTestStatusOut,
    summary="Start or poll assumption stress test job",
)
def start_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    environment = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /environments first.",
        )

    critical_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.sensitivity.in_(["CRITICAL", "HIGH"]),
        )
        .count()
    )
    if critical_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No CRITICAL or HIGH assumptions found. Run assumption extraction first.",
        )

    task = run_assumption_stress_test.delay(project_id)
    return StressTestStatusOut(
        project_id=project_id,
        status="PENDING",
        task_id=task.id,
        result=None,
    )


@router.get(
    "/{project_id}/stress-test",
    response_model=StressTestStatusOut,
    summary="Get stress test status and result",
)
def get_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    raw = getattr(project, "stress_test_json", None)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail="No stress test run yet — call POST /stress-test first",
        )

    status_value = raw.get("status", "UNKNOWN")
    task_id = raw.get("task_id")

    if status_value != "COMPLETED":
        return StressTestStatusOut(
            project_id=project_id,
            status=status_value,
            task_id=task_id,
            result=None,
        )

    matrix = [AssumptionStressResult(**row) for row in raw.get("sensitivity_matrix", [])]
    shots = [AssumptionStressResult(**row) for row in raw.get("kill_shots", [])]

    result = StressTestOut(
        project_id=project_id,
        status="COMPLETED",
        sensitivity_matrix=matrix,
        kill_shots=shots,
        overall_risk_level=raw.get("overall_risk_level", "UNKNOWN"),
        baseline_conversion=raw.get("baseline_conversion", 0.0),
        assumptions_tested=raw.get("assumptions_tested", 0),
        generated_at=raw.get("generated_at", ""),
    )

    return StressTestStatusOut(
        project_id=project_id,
        status="COMPLETED",
        task_id=task_id,
        result=result,
    )


@router.delete(
    "/{project_id}/stress-test",
    summary="Clear stored stress test JSON",
    responses=_JSON_200,
)
def clear_stress_test(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    db.execute(
        text("UPDATE projects SET stress_test_json = NULL WHERE id = :id"),
        {"id": project_id},
    )
    db.commit()
    return {"message": "Stress test result cleared"}


@router.post(
    "/{project_id}/interventions",
    response_model=InterventionOut,
    summary="Generate ranked interventions (Claude)",
)
def generate_interventions(
    project_id: int,
    payload: InterventionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short to generate interventions",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
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

    premortem_data = getattr(project, "premortem_json", None)
    stress_test_data = getattr(project, "stress_test_json", None)

    context_used = {
        "assumptions": len(assumptions) > 0,
        "simulation": latest_sim is not None,
        "premortem": bool(premortem_data and premortem_data.get("failure_modes")),
        "stress_test": bool(stress_test_data and stress_test_data.get("kill_shots")),
    }

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    ranked_findings_text = (
        "\n".join(
            [
                f"{i + 1}. {f.get('finding', '')} → {f.get('recommended_action', '')}"
                for i, f in enumerate(findings[:5])
            ]
        )
        if findings
        else "No findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": INTERVENTION_PROMPT.format(
                        highest_value_cluster=hv_name,
                        primary_failure_domain=primary_fd,
                        cluster_narrative=narrative or "No cluster narrative available.",
                        ranked_findings_text=ranked_findings_text,
                    ),
                }
            ],
            system=(
                "You are an elite startup growth advisor. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Every intervention you suggest is specific, executable, and tied to evidence."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            fallback_key="interventions",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))
        raw_items = parsed.get("interventions", [])
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise ValueError("Claude returned empty interventions list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Intervention generation failed: {str(exc)}",
        )

    interventions: list[Intervention] = []
    for idx, item in enumerate(raw_items):
        try:
            intervention = Intervention(
                id=str(item.get("id", f"int-{idx + 1:02d}")).strip()[:50],
                title=str(item.get("title", "")).strip(),
                description=str(item.get("description", "")).strip(),
                expected_impact=str(item.get("expected_impact", "")).strip(),
                difficulty=str(item.get("difficulty", "MEDIUM")),
                estimated_cost=str(item.get("estimated_cost", "Unknown")).strip(),
                linked_assumption=item.get("linked_assumption") or None,
                linked_failure_mode=item.get("linked_failure_mode") or None,
                priority_score=float(item.get("priority_score", 0.5)),
                time_to_implement=str(item.get("time_to_implement", "Unknown")).strip(),
                success_metric=str(item.get("success_metric", "")).strip(),
            )
            interventions.append(intervention)
        except Exception:
            continue

    if not interventions:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid interventions from Claude response",
        )

    interventions.sort(key=lambda item: item.priority_score, reverse=True)
    max_n = payload.max_interventions if payload else 10
    interventions = interventions[:max_n]

    quick_wins = [
        item for item in interventions if item.difficulty == "LOW" and item.priority_score > 0.70
    ]

    now = datetime.now(timezone.utc).isoformat()
    interventions_data = {
        "interventions": [iv.model_dump() for iv in interventions],
        "quick_wins": [qw.model_dump() for qw in quick_wins],
        "generated_at": now,
        "context_used": context_used,
        "simulation_id": latest_sim.id if latest_sim else None,
    }

    project.interventions_json = interventions_data
    project.status = "INTERVENTIONS_READY"
    db.commit()

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=now,
        context_used=context_used,
    )


@router.get(
    "/{project_id}/interventions",
    response_model=InterventionOut,
    summary="Get stored interventions JSON",
)
def get_interventions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "interventions_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No interventions generated yet — call POST /interventions first",
        )

    interventions = [Intervention(**item) for item in data.get("interventions", [])]
    quick_wins = [Intervention(**item) for item in data.get("quick_wins", [])]

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=data.get("generated_at", ""),
        context_used=data.get("context_used", {}),
    )


@router.post(
    "/{project_id}/competitive-analysis",
    response_model=CompetitiveAnalysisOut,
    summary="Run competitive analysis (Claude)",
)
def run_competitive_analysis(
    project_id: int,
    payload: CompetitiveAnalysisRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    description = (
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short for competitive analysis",
        )

    target_market = (
        payload.target_market if payload and payload.target_market else "Indian startup / SaaS / D2C market"
    )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .limit(5)
        .all()
    )
    assumptions_text = (
        "\n".join(f"- {assumption.text}" for assumption in assumptions)
        if assumptions
        else "No assumptions available."
    )

    try:
        claude_out = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": COMPETITIVE_ANALYSIS_PROMPT.format(
                        description=description,
                        target_market=target_market,
                        assumptions_text=assumptions_text,
                    ),
                }
            ],
            system=(
                "You are a top-tier competitive strategy consultant with deep knowledge "
                "of Indian and global markets. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            fallback_key="competitive",
            timeout=90,
        )
        if claude_out.get("error"):
            raise HTTPException(
                status_code=503,
                detail=str(claude_out.get("error", "Claude unavailable")),
            )
        raw = (claude_out.get("content") or "").strip()
        raw = extract_json_from_markdown(raw)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")
        parsed = json.loads(json_match.group(0))

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Competitive analysis failed: {str(exc)}",
        )

    raw_competitors = parsed.get("competitors", [])
    if not isinstance(raw_competitors, list) or len(raw_competitors) == 0:
        raise HTTPException(
            status_code=500,
            detail="Claude returned no competitors — retry the request",
        )

    competitors: list[Competitor] = []
    for item in raw_competitors:
        try:
            competitors.append(
                Competitor(
                    name=str(item.get("name", "Unknown")).strip(),
                    category=str(item.get("category", "DIRECT")),
                    features=[str(feature) for feature in item.get("features", [])[:8]],
                    pricing=str(item.get("pricing", "Unknown")).strip(),
                    positioning=str(item.get("positioning", "")).strip(),
                    target_segment=str(item.get("target_segment", "")).strip(),
                    strengths=[str(strength) for strength in item.get("strengths", [])[:5]],
                    weaknesses=[str(weakness) for weakness in item.get("weaknesses", [])[:5]],
                    india_presence=str(item.get("india_presence", "MODERATE")),
                    threat_level=str(item.get("threat_level", "MEDIUM")),
                )
            )
        except Exception:
            continue

    if not competitors:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid competitors from Claude response",
        )

    raw_gap = parsed.get("gap_analysis", {})
    gap_analysis = GapAnalysis(
        our_wins=[str(win) for win in raw_gap.get("our_wins", [])[:6]],
        our_losses=[str(loss) for loss in raw_gap.get("our_losses", [])[:6]],
        underserved_segments=[str(segment) for segment in raw_gap.get("underserved_segments", [])[:5]],
        key_differentiators=[str(item) for item in raw_gap.get("key_differentiators", [])[:5]],
        recommended_counter_moves=[str(move) for move in raw_gap.get("recommended_counter_moves", [])[:5]],
    )

    raw_map = parsed.get("market_map", {})
    first_competitor_name = competitors[0].name
    market_map = MarketMap(
        most_dangerous_competitor=str(
            raw_map.get("most_dangerous_competitor", first_competitor_name)
        ),
        easiest_to_displace=str(raw_map.get("easiest_to_displace", first_competitor_name)),
        most_similar_to_us=str(raw_map.get("most_similar_to_us", first_competitor_name)),
    )

    raw_position = str(parsed.get("overall_competitive_position", "MODERATE")).upper().strip()
    position = raw_position if raw_position in VALID_POSITIONS else "MODERATE"
    rationale = str(parsed.get("position_rationale", "")).strip()

    direct_count = sum(1 for competitor in competitors if competitor.category == "DIRECT")
    high_threat_count = sum(1 for competitor in competitors if competitor.threat_level == "HIGH")

    now = datetime.now(timezone.utc).isoformat()
    competitive_data = {
        "competitors": [competitor.model_dump() for competitor in competitors],
        "gap_analysis": gap_analysis.model_dump(),
        "market_map": market_map.model_dump(),
        "overall_competitive_position": position,
        "position_rationale": rationale,
        "generated_at": now,
        "target_market": target_market,
        "assumptions_used": len(assumptions),
    }

    project.competitive_json = competitive_data
    project.status = "COMPETITIVE_ANALYSIS_COMPLETE"
    db.commit()

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=rationale,
        direct_competitor_count=direct_count,
        high_threat_count=high_threat_count,
        generated_at=now,
    )


@router.get(
    "/{project_id}/competitive-analysis",
    response_model=CompetitiveAnalysisOut,
    summary="Get stored competitive analysis JSON",
)
def get_competitive_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    data = getattr(project, "competitive_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No competitive analysis generated yet — call POST /competitive-analysis first",
        )

    competitors = [Competitor(**item) for item in data.get("competitors", [])]
    gap_analysis = GapAnalysis(**data["gap_analysis"])
    market_map = MarketMap(**data["market_map"])
    position = data.get("overall_competitive_position", "MODERATE")

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=data.get("position_rationale", ""),
        direct_competitor_count=sum(1 for competitor in competitors if competitor.category == "DIRECT"),
        high_threat_count=sum(1 for competitor in competitors if competitor.threat_level == "HIGH"),
        generated_at=data.get("generated_at", ""),
    )


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
    status_code=200,
    summary="Create or update market environment parameters for a project",
)
def create_or_update_environment(
    project_id: int,
    payload: EnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    if payload.mode.value == "SCENARIO" and payload.scenario_type:
        preset = SCENARIO_PRESETS.get(payload.scenario_type.value)
        effective = preset or ManualParams()
        if payload.manual_params:
            override = payload.manual_params.model_dump(exclude_none=True)
            merged = effective.model_dump()
            merged.update(override)
            effective = ManualParams(**merged)
    else:
        effective = payload.manual_params or ManualParams()

    existing = db.query(Environment).filter(Environment.project_id == project_id).first()

    if existing:
        existing.mode = payload.mode.value
        existing.consumer_volume = effective.consumer_volume
        existing.growth_rate_per_month = effective.growth_rate_per_month
        existing.average_order_value = effective.average_order_value
        existing.price_sensitivity = effective.price_sensitivity
        existing.market_maturity = effective.market_maturity
        existing.scenario_type = (
            payload.scenario_type.value if payload.scenario_type else None
        )
        existing.manual_params_json = effective.model_dump()
        env = existing
    else:
        env = Environment(
            project_id=project_id,
            mode=payload.mode.value,
            consumer_volume=effective.consumer_volume,
            growth_rate_per_month=effective.growth_rate_per_month,
            average_order_value=effective.average_order_value,
            price_sensitivity=effective.price_sensitivity,
            market_maturity=effective.market_maturity,
            scenario_type=(
                payload.scenario_type.value if payload.scenario_type else None
            ),
            manual_params_json=effective.model_dump(),
        )
        db.add(env)

    project.status = "ENVIRONMENT_SET"
    db.commit()
    db.refresh(env)
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
    summary="Get the environment row for a project",
)
def get_environment(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    env = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not env:
        raise HTTPException(
            status_code=404,
            detail="No environment configured. Call POST /environments first.",
        )
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments/presets",
    response_model=dict,
    summary="List scenario preset parameter bundles",
)
def get_scenario_presets(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all scenario preset configs so the frontend
    can display them to the user before they choose.
    """
    project = get_owned_project(db, current_user.id, project_id)

    return {name: preset.model_dump() for name, preset in SCENARIO_PRESETS.items()}


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Get a single project by id",
)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)
    _backfill_display_precis_lazy(db, project)
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post(
    "/{project_id}/re-simulate",
    summary="Queue a re-simulation and return delta vs previous run",
    responses=_JSON_200,
)
def re_simulate(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Queues a new simulation for the project.
    Compares the two most recent completed runs (newest vs prior).
    Returns delta metrics immediately after queuing.
    """
    project = get_owned_project(db, current_user.id, project_id)

    sims = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .limit(2)
        .all()
    )

    previous_sim = sims[0] if len(sims) >= 1 else None
    older_sim = sims[1] if len(sims) >= 2 else None

    delta: dict | None = None
    if previous_sim and older_sim:
        prev_results = (
            previous_sim.results_json
            if isinstance(previous_sim.results_json, dict)
            else json.loads(previous_sim.results_json or "{}")
        )
        older_results = (
            older_sim.results_json
            if isinstance(older_sim.results_json, dict)
            else json.loads(older_sim.results_json or "{}")
        )

        prev_cr = float(
            prev_results.get("population_weighted_conversion")
            or prev_results.get("conversion_rate")
            or 0
        )
        older_cr = float(
            older_results.get("population_weighted_conversion")
            or older_results.get("conversion_rate")
            or 0
        )
        cr_delta = round(prev_cr - older_cr, 4)

        prev_clusters = prev_results.get("cluster_breakdown", {}) or {}
        older_clusters = older_results.get("cluster_breakdown", {}) or {}

        cluster_deltas: dict[str, float] = {}
        for cid in prev_clusters:
            prev_val = float(
                prev_clusters.get(cid, {}).get("conversion_rate", 0)
                if isinstance(prev_clusters.get(cid), dict)
                else prev_clusters.get(cid, 0)
            )
            older_val = float(
                older_clusters.get(cid, {}).get("conversion_rate", 0)
                if isinstance(older_clusters.get(cid), dict)
                else older_clusters.get(cid, 0)
            )
            cluster_deltas[str(cid)] = round(prev_val - older_val, 4)

        improved = sorted(cluster_deltas.items(), key=lambda x: -x[1])[:3]
        degraded = sorted(cluster_deltas.items(), key=lambda x: x[1])[:3]

        prev_assumptions = prev_results.get("assumptions_summary", []) or []
        older_assumptions = older_results.get("assumptions_summary", []) or []
        changed_count = abs(len(prev_assumptions) - len(older_assumptions))

        direction = "FLAT"
        if cr_delta > 0:
            direction = "UP"
        elif cr_delta < 0:
            direction = "DOWN"

        delta = {
            "conversion_delta": cr_delta,
            "previous_conversion": round(prev_cr, 4),
            "older_conversion": round(older_cr, 4),
            "direction": direction,
            "cluster_deltas": cluster_deltas,
            "most_improved": [
                {"cluster_id": cid, "delta": d} for cid, d in improved if d > 0
            ],
            "most_degraded": [
                {"cluster_id": cid, "delta": d} for cid, d in degraded if d < 0
            ],
            "assumptions_changed": changed_count,
            "simulation_count": len(sims),
        }

    environment = (
        db.query(Environment).filter(Environment.project_id == project_id).first()
    )
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /api/v1/projects/{id}/environments first.",
        )

    running = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status.in_(["QUEUED", "RUNNING"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation {running.id} is already {running.status} for this project.",
        )

    new_sim = Simulation(
        project_id=project_id,
        environment_id=environment.id,
        status="QUEUED",
        consumer_volume=environment.consumer_volume,
    )
    db.add(new_sim)
    db.commit()
    db.refresh(new_sim)

    task = run_full_simulation.delay(new_sim.id)
    new_sim.task_id = task.id
    db.commit()
    db.refresh(new_sim)

    return {
        "new_simulation_id": new_sim.id,
        "status": "QUEUED",
        "delta": delta,
        "message": (
            "Re-simulation queued. Delta from previous run included."
            if delta
            else "First simulation queued. No previous run to compare."
        ),
    }


@router.get(
    "/{project_id}/simulation-history",
    summary="List completed runs with key metrics for charts",
    responses=_JSON_200,
)
def get_simulation_history(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sims = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.asc())
        .all()
    )

    history: list[dict] = []
    prev_cr: float | None = None
    for sim in sims:
        results = (
            sim.results_json
            if isinstance(sim.results_json, dict)
            else json.loads(sim.results_json or "{}")
        )
        cr = float(
            results.get("population_weighted_conversion")
            or results.get("conversion_rate")
            or 0
        )
        delta_cr = round(cr - prev_cr, 4) if prev_cr is not None else None
        if delta_cr is not None and delta_cr > 0:
            direction = "UP"
        elif delta_cr is not None and delta_cr < 0:
            direction = "DOWN"
        else:
            direction = "FLAT" if delta_cr is not None else None
        history.append(
            {
                "simulation_id": sim.id,
                "status": sim.status,
                "signal_quality": sim.signal_quality,
                "conversion_rate": round(cr, 4),
                "delta_from_prev": delta_cr,
                "direction": direction,
                "created_at": sim.created_at.isoformat() if sim.created_at else None,
            }
        )
        prev_cr = cr

    return {
        "project_id": project_id,
        "total_runs": len(history),
        "history": history,
        "best_run_id": max(history, key=lambda x: x["conversion_rate"])["simulation_id"]
        if history
        else None,
    }


@router.post(
    "/{project_id}/competitive-software-analysis",
    summary="Run SaaS / software competitive benchmark analysis",
    responses=_JSON_200,
)
def run_competitive_software_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not sim:
        raise HTTPException(
            status_code=400,
            detail="Run a simulation first before competitive analysis",
        )

    results = sim.results_json
    if isinstance(results, str):
        results = json.loads(results or "{}")
    if not isinstance(results, dict):
        results = {}

    product_type_str = str(results.get("product_type_detected", "saas")).strip().lower()
    pt_enum = _product_type_enum_from_results(product_type_str)
    pt_for_conductor = pt_enum if pt_enum in _SOFTWARE_PRODUCT_TYPES else ProductType.SAAS

    aov = float(results.get("aov") or results.get("average_order_value") or 999.0)

    assumption_rows = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.created_at.desc())
        .all()
    )
    assumptions = [
        {
            "assumption": a.text,
            "text": a.text,
            "sensitivity": a.sensitivity or "MEDIUM",
            "claim_confidence": "DESIGN_INTENT",
        }
        for a in assumption_rows
    ]

    env_params = {
        "average_order_value": aov,
        "description": project.description or "",
    }
    sq = float(sim.signal_quality or 0.0)

    conductor_result = _conductor.run(
        agents=[],
        env_params=env_params,
        assumptions=assumptions,
        product_type=pt_for_conductor,
        signal_quality=sq,
    )

    report = _comp_software_analyser.analyse(
        assumptions=assumptions,
        conductor_result=conductor_result,
        product_type=_software_benchmark_key(pt_enum),
        aov=aov,
    )

    merged = {**results, "competitive_analysis": report.to_dict()}
    sim.results_json = merged
    db.add(sim)
    db.commit()
    return report.to_dict()


@router.get(
    "/{project_id}/competitive-software-analysis",
    summary="Get stored software competitive analysis JSON",
    responses=_JSON_200,
)
def get_competitive_software_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if not sim:
        return {
            "message": "No completed simulation. POST to /competitive-software-analysis first."
        }

    results = sim.results_json
    if isinstance(results, str):
        results = json.loads(results or "{}")
    if not isinstance(results, dict):
        results = {}

    comp = results.get("competitive_analysis")
    if not comp:
        return {
            "message": "No competitive analysis yet. POST to /competitive-software-analysis."
        }
    return comp


@router.post(
    "/{project_id}/regenerate-intelligence",
    response_model=ProjectOut,
    summary="Regenerate Précis and Readings for a project",
)
def regenerate_intelligence(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == current_user.id,
        )
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    from app.services.dossier_intelligence import generate_both, readings_json_payload

    intel = generate_both(project.title, project.description)

    if intel["precis"]:
        project.precis = intel["precis"]
    bundle = readings_json_payload(
        intel["readings"],
        intel.get("ledger") or {},
    )
    if bundle:
        project.readings_json = bundle
    project.precis_title_fingerprint = _title_fingerprint(project.title)

    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)
