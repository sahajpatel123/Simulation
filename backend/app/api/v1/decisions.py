from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.decision import Decision
from app.models.environment import Environment
from app.models.project import Project
from app.models.user import User
from app.schemas.decision import (
    DecisionCreate,
    DecisionOut,
    DecisionStatusOut,
    ScenarioResult,
)
from app.tasks.decision_tasks import run_decision_comparison

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["decisions"])


def _hydrate_result(decision: Decision) -> DecisionOut | None:
    data = decision.results_json
    if not data or decision.status != "COMPLETED":
        return None

    scenario_results = [ScenarioResult(**scenario) for scenario in data.get("scenarios", [])]
    return DecisionOut(
        id=decision.id,
        project_id=decision.project_id,
        title=decision.title,
        description=decision.description or "",
        status=decision.status,
        scenarios=scenario_results,
        recommended_scenario=data.get("recommended_scenario"),
        winner_margin=data.get("winner_margin", 0.0),
        key_insights=data.get("key_insights", []),
        task_id=decision.task_id,
        generated_at=data.get("generated_at"),
    )


@router.post(
    "/{project_id}/decisions",
    response_model=DecisionStatusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enqueue a multi-scenario decision comparison",
)
def create_decision_comparison(
    project_id: int,
    payload: DecisionCreate,
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

    environment = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /environments first.",
        )

    decision = Decision(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        status="PENDING",
        results_json={
            "scenarios_input": [
                {
                    "name": scenario.name,
                    "description": scenario.description,
                    "parameters": scenario.parameters.model_dump(exclude_none=True),
                }
                for scenario in payload.scenarios
            ]
        },
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    task = run_decision_comparison.delay(decision.id)
    decision.task_id = task.id
    db.commit()

    logger.info(
        "[API] Decision comparison enqueued — decision_id=%s task_id=%s",
        decision.id,
        task.id,
    )

    return DecisionStatusOut(
        id=decision.id,
        project_id=project_id,
        title=decision.title,
        status="PENDING",
        task_id=task.id,
        result=None,
    )


@router.get(
    "/{project_id}/decisions/{decision_id}",
    response_model=DecisionStatusOut,
    summary="Get a single decision job and its result if complete",
)
def get_decision_comparison(
    project_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    decision = _get_owned_decision(project_id, decision_id, current_user.id, db)
    return DecisionStatusOut(
        id=decision.id,
        project_id=decision.project_id,
        title=decision.title,
        status=decision.status,
        task_id=decision.task_id,
        result=_hydrate_result(decision),
    )


@router.get(
    "/{project_id}/decisions",
    response_model=list[DecisionStatusOut],
    summary="List decision comparisons for a project",
)
def list_decisions(
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

    decisions = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .order_by(Decision.created_at.desc())
        .all()
    )
    return [
        DecisionStatusOut(
            id=decision.id,
            project_id=decision.project_id,
            title=decision.title,
            status=decision.status,
            task_id=decision.task_id,
            result=_hydrate_result(decision),
        )
        for decision in decisions
    ]


def _get_owned_decision(
    project_id: int,
    decision_id: int,
    user_id: int,
    db: Session,
) -> Decision:
    decision = (
        db.query(Decision)
        .join(Project, Decision.project_id == Project.id)
        .filter(
            Decision.id == decision_id,
            Decision.project_id == project_id,
            Project.user_id == user_id,
        )
        .first()
    )
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision
