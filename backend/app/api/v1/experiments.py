"""
A/B landing-page experiment routes.

The simulation engine recommends concrete micro-tests (landing-page A/B
experiments, pricing tests, messaging variants); these endpoints let a
founder paste the observed results back and get a statistical verdict, and
keep a durable per-project registry of the tests they have actually run:

* ``POST /experiments/ab-analysis`` — stateless statistical verdict.
* ``POST /projects/{project_id}/experiments`` — log a persisted experiment.
* ``GET /projects/{project_id}/experiments`` — list logged experiments.
* ``GET /projects/{project_id}/experiments/{experiment_id}`` — fetch one.
* ``PATCH /projects/{project_id}/experiments/{experiment_id}`` — correct
  counts / params and recompute the verdict.
* ``DELETE /projects/{project_id}/experiments/{experiment_id}`` — remove a
  mis-logged or abandoned test.

All routes are pure computation / local DB writes — no Celery dispatch, no
LLM calls.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.models.ab_test_experiment import AbTestExperiment
from app.models.project import Project
from app.models.user import User
from app.schemas.ab_test import (
    AbTestAnalysisIn,
    AbTestAnalysisOut,
    AbTestExperimentCreate,
    AbTestExperimentOut,
    AbTestExperimentUpdate,
)
from app.simulation import ab_test_analysis as ab_engine

router = APIRouter(tags=["experiments"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}
_JSON_201 = {201: {"description": "Created", "content": {"application/json": {}}}}
_JSON_204 = {204: {"description": "Deleted"}}


def _apply_analysis(row: AbTestExperiment, analysis: dict[str, Any]) -> None:
    """Persist a fresh analysis snapshot onto an experiment row."""
    variant_a = analysis["variant_a"]
    variant_b = analysis["variant_b"]
    row.variant_a_label = str(variant_a["label"])
    row.variant_b_label = str(variant_b["label"])
    row.visitors_a = int(variant_a["visitors"])
    row.conversions_a = int(variant_a["conversions"])
    row.visitors_b = int(variant_b["visitors"])
    row.conversions_b = int(variant_b["conversions"])
    row.alpha = float(analysis["meta"]["alpha"])
    row.power = float(analysis["meta"]["power"])
    row.mde = float(analysis["meta"]["mde"])
    row.verdict = str(analysis["verdict"])
    row.significant = bool(analysis["significant"])
    row.winner = analysis.get("winner")
    row.absolute_uplift = analysis.get("absolute_uplift")
    row.relative_uplift_pct = analysis.get("relative_uplift_pct")
    row.z_score = analysis.get("z_score")
    row.p_value = analysis.get("p_value")
    row.analysis_json = analysis


def _owned_experiment(
    db: Session,
    user_id: int,
    project_id: int,
    experiment_id: int,
) -> AbTestExperiment:
    """Fetch an experiment by ID, scoped to a project owned by the user."""
    row = (
        db.query(AbTestExperiment)
        .join(Project, AbTestExperiment.project_id == Project.id)
        .filter(
            AbTestExperiment.id == experiment_id,
            AbTestExperiment.project_id == project_id,
            Project.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="A/B experiment not found",
        )
    return row


def _analysis_out(row: AbTestExperiment) -> AbTestAnalysisOut:
    """Hydrate the full analysis payload for a stored experiment.

    Prefers the denormalised ``analysis_json`` snapshot so responses stay
    byte-stable, but falls back to recomputing from the NOT NULL
    denormalised columns when the snapshot is missing or corrupted (a row
    written by another writer, a partial migration, manual DB edit) so one
    bad JSONB blob can never 500 a list or detail read.
    """
    if row.analysis_json:
        try:
            return AbTestAnalysisOut(**row.analysis_json)
        except (TypeError, ValidationError):
            pass
    return AbTestAnalysisOut(
        **ab_engine.analyze_ab_test(
            {
                "label": row.variant_a_label,
                "visitors": row.visitors_a,
                "conversions": row.conversions_a,
            },
            {
                "label": row.variant_b_label,
                "visitors": row.visitors_b,
                "conversions": row.conversions_b,
            },
            alpha=row.alpha,
            power=row.power,
            mde=row.mde,
        )
    )


def _hydrate_experiment(row: AbTestExperiment) -> AbTestExperimentOut:
    """Render one experiment; top-level snapshot fields always match the
    nested analysis payload even when a stored snapshot needed a fallback."""
    analysis = _analysis_out(row)
    return AbTestExperimentOut(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        hypothesis=row.hypothesis,
        analysis=analysis,
        verdict=analysis.verdict,
        significant=analysis.significant,
        winner=analysis.winner,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/experiments/ab-analysis",
    response_model=AbTestAnalysisOut,
    summary="Analyse a two-variant A/B landing-page experiment",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def analyze_ab_test(
    payload: AbTestAnalysisIn,
    current_user: User = Depends(get_current_user),
) -> AbTestAnalysisOut:
    """
    Return a statistical verdict for two observed A/B arms (visitors +
    conversions each): significance, uplift, confidence interval, and how
    much more traffic the test needs. Inputs are validated by the schema
    (conversions must not exceed visitors, counts must be finite ints), and
    the analysis is deliberately conservative — it refuses to report
    p-values until the test has enough traffic to be meaningful.
    """
    result = ab_engine.analyze_ab_test(
        payload.variant_a,
        payload.variant_b,
        alpha=payload.alpha,
        power=payload.power,
        mde=payload.minimum_detectable_effect,
    )
    return AbTestAnalysisOut(**result)


@router.post(
    "/projects/{project_id}/experiments",
    response_model=AbTestExperimentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a persistent A/B landing-page experiment for a project",
    responses=_JSON_201,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def create_ab_test_experiment(
    project_id: int,
    payload: AbTestExperimentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AbTestExperimentOut:
    """
    Persist one observed A/B experiment (arms + statistical parameters)
    under the project and return it with its computed verdict snapshot.
    Reuses the same conservative analysis as the stateless endpoint, so a
    logged test can never disagree with ``POST /experiments/ab-analysis``
    for the same numbers.
    """
    project = get_owned_project(db, current_user.id, project_id)
    analysis = ab_engine.analyze_ab_test(
        payload.analysis.variant_a,
        payload.analysis.variant_b,
        alpha=payload.analysis.alpha,
        power=payload.analysis.power,
        mde=payload.analysis.minimum_detectable_effect,
    )

    row = AbTestExperiment(
        project_id=project.id,
        name=payload.name,
        hypothesis=payload.hypothesis,
    )
    _apply_analysis(row, analysis)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _hydrate_experiment(row)


@router.get(
    "/projects/{project_id}/experiments",
    response_model=list[AbTestExperimentOut],
    summary="List persisted A/B experiments for a project",
    responses=_JSON_200,
)
def list_ab_test_experiments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AbTestExperimentOut]:
    """
    Return every logged A/B experiment for the project, newest first, with
    each test's stored statistical verdict. Read-only and cheap: verdicts
    are snapshot columns, so no statistics are recomputed on list.
    """
    get_owned_project(db, current_user.id, project_id)
    rows = (
        db.query(AbTestExperiment)
        .filter(AbTestExperiment.project_id == project_id)
        .order_by(
            AbTestExperiment.created_at.desc(),
            AbTestExperiment.id.desc(),
        )
        .all()
    )
    return [_hydrate_experiment(row) for row in rows]


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}",
    response_model=AbTestExperimentOut,
    summary="Fetch one persisted A/B experiment",
    responses=_JSON_200,
)
def get_ab_test_experiment(
    project_id: int,
    experiment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AbTestExperimentOut:
    """Return one logged experiment with its stored verdict snapshot."""
    row = _owned_experiment(db, current_user.id, project_id, experiment_id)
    return _hydrate_experiment(row)


@router.patch(
    "/projects/{project_id}/experiments/{experiment_id}",
    response_model=AbTestExperimentOut,
    summary="Correct a persisted A/B experiment and recompute its verdict",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def update_ab_test_experiment(
    project_id: int,
    experiment_id: int,
    payload: AbTestExperimentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AbTestExperimentOut:
    """
    Update the experiment's name, hypothesis, and/or observed arms. When
    ``analysis`` is supplied, the verdict snapshot is recomputed from the
    new numbers so a corrected count never leaves a stale verdict behind.
    """
    row = _owned_experiment(db, current_user.id, project_id, experiment_id)

    if "name" in payload.model_fields_set:
        row.name = payload.name
    if "hypothesis" in payload.model_fields_set:
        row.hypothesis = payload.hypothesis
    if payload.analysis is not None:
        analysis = ab_engine.analyze_ab_test(
            payload.analysis.variant_a,
            payload.analysis.variant_b,
            alpha=payload.analysis.alpha,
            power=payload.analysis.power,
            mde=payload.analysis.minimum_detectable_effect,
        )
        _apply_analysis(row, analysis)

    db.commit()
    db.refresh(row)
    return _hydrate_experiment(row)


@router.delete(
    "/projects/{project_id}/experiments/{experiment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a persisted A/B experiment",
    responses=_JSON_204,
    # Destructive — cap path-spam at 10/min/IP so a runaway script
    # can't churn through deletes.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def delete_ab_test_experiment(
    project_id: int,
    experiment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Remove a mis-logged or abandoned experiment from the registry."""
    row = _owned_experiment(db, current_user.id, project_id, experiment_id)
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
