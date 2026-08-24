"""One-call per-project overview endpoint.

Composes the ten existing per-project digest endpoints into a single
dashboard payload, mirroring how ``/api/v1/system/overview`` composes the
subsystem health digests. A dashboard can render the project header with one
request instead of ten, and the overview-level cache absorbs polling while
each panel keeps its own 60s cache for the individual endpoints.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.api.v1.outcomes import get_outcomes_digest
from app.api.v1.projects import (
    get_confidence_explainer,
    get_convergence_check,
    get_latest_snapshot,
    get_next_action,
    get_project_health,
    get_project_simulation_quality,
    get_stale_check,
    get_status_banner,
)
from app.api.v1.simulations import get_prediction_range
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.response_cache import cache_get_json, cache_set_json
from app.core.security import log_safe
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.project_overview import ProjectOverviewOut
from app.simulation.project_overview import build_project_overview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])

_PROJECT_OVERVIEW_CACHE_NAMESPACE: str = "project-overview"
_PROJECT_OVERVIEW_CACHE_TTL_S: int = 60


def _latest_prediction_range_loader(
    project_id: int,
    db: Session,
    current_user: User,
) -> Any:
    """Load the project's latest completed-run prediction range, if any.

    The prediction-range endpoint is per-simulation, while every other
    overview panel is per-project. This loader resolves the project's newest
    completed run (with persisted results) and delegates to the same route
    function the per-simulation endpoint uses, so the overview panel cannot
    drift from the standalone digest.
    """
    latest = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
            Simulation.results_json.isnot(None),
        )
        .order_by(Simulation.created_at.desc(), Simulation.id.desc())
        .first()
    )
    if latest is None:
        return None
    return get_prediction_range(latest.id, db, current_user)


# Canonical (panel key, loader attribute name) pairs in dashboard display
# order. Each loader is an existing route function with the same signature,
# resolved at call time so the overview always reflects exactly what the
# individual endpoints return (and stays monkeypatch-friendly in tests).
_PANEL_LOADER_NAMES: tuple[tuple[str, str], ...] = (
    ("status_banner", get_status_banner.__name__),
    ("latest_snapshot", get_latest_snapshot.__name__),
    ("simulation_quality", get_project_simulation_quality.__name__),
    ("prediction_range", _latest_prediction_range_loader.__name__),
    ("confidence_explainer", get_confidence_explainer.__name__),
    ("next_action", get_next_action.__name__),
    ("stale_check", get_stale_check.__name__),
    ("convergence", get_convergence_check.__name__),
    ("health", get_project_health.__name__),
    ("outcomes_digest", get_outcomes_digest.__name__),
)


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewOut,
    summary=(
        "One-call per-project dashboard digest - composes status banner, "
        "latest snapshot, simulation quality, prediction range, confidence "
        "explainer, next action, stale check, convergence, health and "
        "outcome accuracy into a single payload with an overall verdict"
    ),
    # Composes ten bounded read-only digests, so cap polling the way the
    # other lightweight project endpoints are capped.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_project_overview(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOverviewOut:
    """Return the one-call per-project overview payload.

    Every panel is produced by the same route function that serves the
    individual digest endpoint, so the composed payload cannot drift from
    what those endpoints return. One digest failing fails open (the panel is
    omitted as unavailable) rather than taking down the whole dashboard.
    """
    get_owned_project(db, current_user.id, project_id)

    cached = cache_get_json(
        namespace=_PROJECT_OVERVIEW_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
    )
    if cached is not None:
        return ProjectOverviewOut(**cached)

    panels: dict[str, Any] = {}
    for key, loader_name in _PANEL_LOADER_NAMES:
        loader = globals().get(loader_name)
        if loader is None:
            continue
        try:
            model = loader(project_id, db, current_user)
            if model is None:
                panels[key] = None
            else:
                panels[key] = (
                    model.model_dump()
                    if hasattr(model, "model_dump")
                    else dict(model)
                )
        except Exception as exc:  # noqa: BLE001 - fail open per panel
            logger.warning(
                "project overview: %s panel failed for project %s: %s",
                key,
                log_safe(project_id).replace("\n", " "),
                log_safe(exc).replace("\n", " "),
            )

    payload = build_project_overview(
        project_id=project_id,
        generated_at=datetime.now(UTC).isoformat(),
        panels=panels,
    )
    cache_set_json(
        namespace=_PROJECT_OVERVIEW_CACHE_NAMESPACE,
        params={"project_id": project_id},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=_PROJECT_OVERVIEW_CACHE_TTL_S,
    )
    return ProjectOverviewOut(**payload)
