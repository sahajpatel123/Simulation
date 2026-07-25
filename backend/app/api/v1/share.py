"""
Public share-token endpoints.

  * ``POST   /api/v1/simulations/{id}/share``  — owner mints a token
  * ``GET    /api/v1/share/{token}``           — anyone reads the result
  * ``DELETE /api/v1/simulations/{id}/share``  — owner revokes all tokens

The GET endpoint is intentionally auth-free: the token *is* the credential.
Only the SHA-256 hash of the token is persisted, so a leaked DB row can't
be used to mint live links.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.models.project import Project
from app.models.share_token import ShareToken
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.share import (
    SharedSimulationOut,
    ShareTokenCreateIn,
    ShareTokenOut,
)
from app.simulation.share_token import (
    anonymise_simulation,
    compute_expiry,
    generate_token,
    hash_token,
    is_expired,
)

logger = logging.getLogger(__name__)

# Two routers: one auth-protected under /simulations, one public under /share.
# They share the same module so the URL path shape is co-located with the handler.
_protected = APIRouter(prefix="/simulations", tags=["share"])
_public = APIRouter(prefix="/share", tags=["share"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


# ---------------------------------------------------------------------------
# Owner: mint a share token
# ---------------------------------------------------------------------------


@_protected.post(
    "/{simulation_id}/share",
    response_model=ShareTokenOut,
    status_code=201,
    summary="Mint a read-only share token for a completed simulation",
    responses=_JSON_200,
    # Auth-required mutating route — the per-user quota is the main gate,
    # but cap path-spam at 10/min/IP so a single actor can't probe live sim IDs.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def create_share_token(
    simulation_id: int,
    payload: ShareTokenCreateIn | None = None,  # body is currently empty but reserved
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShareTokenOut:
    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == current_user.id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot share a simulation in status {sim.status!r}. "
                "Wait until it completes."
            ),
        )

    token = generate_token()
    token_hash = hash_token(token)
    expires_at = compute_expiry()

    row = ShareToken(
        simulation_id=sim.id,
        user_id=current_user.id,
        token_hash=token_hash,
        scope="read_only",
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "[Share] Token minted — simulation_id=%s user_id=%s share_id=%s",
        sim.id,
        current_user.id,
        row.id,
    )

    return ShareTokenOut(
        token=token,
        simulation_id=sim.id,
        scope=row.scope,
        expires_at=row.expires_at,
        created_at=row.created_at,
        share_url=f"/api/v1/share/{token}",
    )


# ---------------------------------------------------------------------------
# Owner: revoke all live tokens for a sim
# ---------------------------------------------------------------------------


@_protected.delete(
    "/{simulation_id}/share",
    summary="Revoke all active share tokens for a simulation",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def revoke_share_tokens(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == current_user.id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")

    now = datetime.now(timezone.utc)
    live_rows = (
        db.query(ShareToken)
        .filter(
            ShareToken.simulation_id == sim.id,
            ShareToken.revoked_at.is_(None),
        )
        .all()
    )
    revoked = 0
    for row in live_rows:
        if not is_expired(row.expires_at, now=now):
            row.revoked_at = now
            revoked += 1
    db.commit()

    logger.info(
        "[Share] Tokens revoked — simulation_id=%s user_id=%s revoked=%s",
        sim.id,
        current_user.id,
        revoked,
    )
    return {
        "simulation_id": sim.id,
        "revoked_count": revoked,
        "revoked_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Public: read by token (no auth)
# ---------------------------------------------------------------------------


@_public.get(
    "/{token}",
    response_model=SharedSimulationOut,
    summary="Public read-only view of a shared simulation (token is the credential)",
    responses=_JSON_200,
    # Public endpoint — a leaked token is the only credential. Cap path
    # abuse at 30/min/IP so a flooder can't trigger arbitrary hash work.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def read_shared_simulation(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> SharedSimulationOut:
    if not token or len(token) > 128:
        raise HTTPException(status_code=400, detail="Invalid token")

    token_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    row = (
        db.query(ShareToken)
        .filter(ShareToken.token_hash == token_hash)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Unknown or invalid token")
    if row.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Token has been revoked")
    if is_expired(row.expires_at, now=now):
        raise HTTPException(status_code=410, detail="Token has expired")

    sim = db.query(Simulation).filter(Simulation.id == row.simulation_id).first()
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")

    project = db.query(Project).filter(Project.id == sim.project_id).first()

    # Best-effort access tracking — never fail the request if the UPDATE
    # errors (the share is the user-facing promise; bookkeeping is secondary).
    try:
        row.last_accessed_at = now
        row.access_count = (row.access_count or 0) + 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("[Share] access tracking failed — share_id=%s", row.id)

    payload = anonymise_simulation(
        sim_row={
            "id": sim.id,
            "status": sim.status,
            "signal_quality": sim.signal_quality,
            "results_json": sim.results_json,
        },
        project_row={"title": project.title} if project else None,
        shared_at=row.created_at,
        expires_at=row.expires_at,
    )
    return SharedSimulationOut(**payload)


# ---------------------------------------------------------------------------
# Module-level router for ``app.api.v1.__init__`` to import
# ---------------------------------------------------------------------------


router = APIRouter()
router.include_router(_protected)
router.include_router(_public)


__all__ = ["router"]