from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.api.v1.projects import (
    _ACTIVITY_FEED_CACHE_NAMESPACE,
    _ADOPTION_MILESTONES_CACHE_NAMESPACE,
    _LATEST_SNAPSHOT_CACHE_NAMESPACE,
    _NEXT_ACTION_CACHE_NAMESPACE,
    _PROJECT_HEALTH_CACHE_NAMESPACE,
    _STALE_CHECK_CACHE_NAMESPACE,
)
from app.api.v1.users import (
    _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE,
    _USER_DASHBOARD_CACHE_NAMESPACE,
    _USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE,
    _USER_NOTIFICATIONS_CACHE_NAMESPACE,
    _USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
    _USER_PROJECTS_SUMMARY_CACHE_NAMESPACE,
    _USER_QUICK_STATS_CACHE_NAMESPACE,
    _USER_USAGE_BY_WEEK_CACHE_NAMESPACE,
    _USER_WEEKLY_DIGEST_CACHE_NAMESPACE,
)
from app.api.v1.projects import (
    _STATUS_BANNER_CACHE_NAMESPACE,
)
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import (
    cache_get_json,
    cache_invalidate,
    cache_set_json,
)
from app.models.decision import Decision
from app.models.environment import Environment
from app.models.project import Project
from app.models.user import User
from app.schemas.decision import (
    DecisionCreate,
    DecisionDigestOut,
    DecisionOut,
    DecisionStatusOut,
    ScenarioResult,
)
from app.simulation.decision_digest import build_decision_digest
from app.tasks.decision_tasks import run_decision_comparison

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["decisions"])

# Decisions move slower than simulation results — a new
# decision is created, runs for seconds-to-minutes, then
# the digest is stable. 60s TTL absorbs dashboard polling
# without making a just-completed decision look stale.
_DECISION_DIGEST_CACHE_TTL_S: int = 60
_DECISION_DIGEST_CACHE_NAMESPACE: str = "decision-digest"


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
    # Celery-backed; cap path-spam so a single actor can't drain the
    # worker queue. Same shape as the simulations POST rate limit.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def create_decision_comparison(
    project_id: int,
    payload: DecisionCreate,
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

    # Bust the cached decision-digest + the per-project
    # next-action + the activity feed so the new PENDING
    # row surfaces immediately on the next GET (the
    # digest, the CTA, AND the timeline all care).
    cache_invalidate(
        namespace=_DECISION_DIGEST_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_NEXT_ACTION_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ACTIVITY_FEED_CACHE_NAMESPACE,
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
        namespace=_USER_NOTIFICATIONS_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_ADOPTION_MILESTONES_CACHE_NAMESPACE,
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
        namespace=_LATEST_SNAPSHOT_CACHE_NAMESPACE,
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
        namespace=_STATUS_BANNER_CACHE_NAMESPACE,
        user_id=current_user.id,
    )
    cache_invalidate(
        namespace=_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE,
        user_id=current_user.id,
    )

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
    get_owned_project(db, current_user.id, project_id)

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


@router.get(
    "/{project_id}/decision-digest",
    response_model=DecisionDigestOut,
    summary=(
        "Per-project digest of AI-generated decisions — "
        "status breakdown + pending action queue + top "
        "completed decisions + narrative + key_signals"
    ),
    # Read-only aggregation over the project's decision
    # rows; same cap as the other list endpoint.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_decision_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionDigestOut:
    """Per-project decision digest.

    Composes a single payload covering status counts,
    pending action queue, top completed decisions, and a
    founder-readable narrative. Avoids the round-trip
    cost of /projects/{id}/decisions + client-side
    aggregation for the dashboard's project overview tile.
    """
    get_owned_project(db, current_user.id, project_id)

    # Cache hit → short-circuit the SELECT. Key is
    # namespaced by user + project so tenants and projects
    # never collide.
    cached = cache_get_json(
        namespace=_DECISION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return DecisionDigestOut(**cached)

    rows = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .order_by(Decision.created_at.desc())
        .all()
    )
    decision_dicts = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "created_at": d.created_at,
            "results_json": d.results_json,
        }
        for d in rows
    ]
    payload = build_decision_digest(decision_dicts)

    cache_set_json(
        namespace=_DECISION_DIGEST_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_DECISION_DIGEST_CACHE_TTL_S,
    )
    return DecisionDigestOut(**payload)


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
