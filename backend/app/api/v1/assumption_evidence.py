"""
Assumption-evidence log and de-risking scorecard routes.

The validation-experiment planner says *what* to run; these endpoints let a
founder record *what happened* and see the consequence:

* ``POST /projects/{project_id}/assumptions/{assumption_id}/evidence``
  logs one experiment result (method + PASS/FAIL/INCONCLUSIVE).
* ``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard``
  returns the evidence history plus the before/after validation-ROI shift
  implied by the derived confidence tier.
* ``GET /projects/{project_id}/evidence-digest`` rolls every logged
  experiment up into a project-level de-risking summary.

Pure post-hoc analysis — no Celery dispatch, no LLM calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.models.assumption import Assumption
from app.models.assumption_evidence import AssumptionEvidence
from app.models.environment import Environment
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.assumption_evidence import (
    AssumptionEvidenceDigestOut,
    AssumptionEvidenceScorecardOut,
    EvidenceCreate,
    EvidenceOut,
)
from app.simulation.assumption_evidence_digest import (
    build_assumption_evidence_digest,
)
from app.simulation.evidence_scorecard import (
    build_assumption_scorecard,
    derive_confidence,
    evidence_to_out,
)

router = APIRouter(prefix="/projects", tags=["assumption-evidence"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _assumption_or_404(
    db: Session, project_id: int, assumption_id: int
) -> Assumption:
    assumption = (
        db.query(Assumption)
        .filter(
            Assumption.id == assumption_id,
            Assumption.project_id == project_id,
        )
        .first()
    )
    if not assumption:
        raise HTTPException(
            status_code=404, detail="Assumption not found in this project"
        )
    return assumption


@router.post(
    "/{project_id}/assumptions/{assumption_id}/evidence",
    response_model=EvidenceOut,
    summary="Log a validation experiment result for an assumption",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def create_assumption_evidence(
    project_id: int,
    assumption_id: int,
    payload: EvidenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceOut:
    """
    Record the outcome of one validation experiment (method + PASS/FAIL/
    INCONCLUSIVE) against an assumption. A PASS upgrades the assumption's
    derived confidence to ``VALIDATED_INTERNAL``; a FAIL drops it to
    ``ASPIRATIONAL``; INCONCLUSIVE leaves it unchanged.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumption = _assumption_or_404(db, project.id, assumption_id)

    row = AssumptionEvidence(
        project_id=project.id,
        assumption_id=assumption.id,
        method=payload.method,
        result=payload.result,
        observed_metric=payload.observed_metric,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    derived = derive_confidence(row.result)
    return EvidenceOut(
        id=row.id,
        project_id=row.project_id,
        assumption_id=row.assumption_id,
        assumption_text=assumption.text,
        method=row.method,
        method_label=evidence_to_out(row, assumption.text).method_label,
        result=row.result,
        observed_metric=row.observed_metric,
        notes=row.notes,
        created_at=row.created_at,
        derived_confidence=derived.value if derived is not None else None,
    )


@router.get(
    "/{project_id}/assumptions/{assumption_id}/evidence-scorecard",
    response_model=AssumptionEvidenceScorecardOut,
    summary="De-risking scorecard: evidence history + validation-ROI shift",
    responses=_JSON_200,
)
def get_assumption_evidence_scorecard(
    project_id: int,
    assumption_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionEvidenceScorecardOut:
    """
    De-risking scorecard for one assumption: every logged experiment, the
    evidence-derived confidence tier, and how validation-ROI (and its tier)
    would shift if the derived confidence were applied today.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumption = _assumption_or_404(db, project.id, assumption_id)

    evidence = (
        db.query(AssumptionEvidence)
        .filter(
            AssumptionEvidence.project_id == project.id,
            AssumptionEvidence.assumption_id == assumption.id,
        )
        .order_by(AssumptionEvidence.created_at.desc(), AssumptionEvidence.id.desc())
        .all()
    )

    sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project.id)
        .order_by(Simulation.created_at.desc(), Simulation.id.desc())
        .first()
    )
    if sim is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No simulation found for this project — run a simulation before "
                "requesting an evidence scorecard."
            ),
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Latest simulation is {sim.status} — evidence scorecards "
                "require completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Latest simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment).filter(Environment.id == sim.environment_id).first()
    )
    env_params: dict = {}
    if environment:
        env_params = {
            "average_order_value": float(environment.average_order_value or 999.0),
            "price_sensitivity": float(environment.price_sensitivity or 0.5),
            "market_maturity": float(environment.market_maturity or 0.3),
            "consumer_volume": int(environment.consumer_volume or 10000),
            "growth_rate_per_month": float(environment.growth_rate_per_month or 5.0),
        }

    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .all()
    )

    return build_assumption_scorecard(
        simulation_id=sim.id,
        project_id=project.id,
        assumption=assumption,
        evidence=evidence,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
    )


@router.get(
    "/{project_id}/evidence-digest",
    response_model=AssumptionEvidenceDigestOut,
    summary="Project-level validation-evidence digest",
    responses=_JSON_200,
)
def get_assumption_evidence_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionEvidenceDigestOut:
    """
    Roll every logged validation experiment for the project up into one
    de-risking digest: evidence coverage, de-risked / challenged /
    pending counts, result and method histograms, and the top
    experiments still worth running. Unlike the per-assumption scorecard,
    this endpoint does not require a completed simulation — a founder can
    track validation progress as soon as experiments are logged.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.desc(),
            AssumptionEvidence.id.desc(),
        )
        .all()
    )
    return AssumptionEvidenceDigestOut(
        **build_assumption_evidence_digest(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )
