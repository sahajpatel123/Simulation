"""CRUD + ping API for simulation-completion webhook subscriptions."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.models.user import User
from app.schemas.simulation_webhooks import (
    SimulationWebhookCreate,
    SimulationWebhookListOut,
    SimulationWebhookOut,
    SimulationWebhookUpdate,
)
from app.simulation.simulation_webhook_delivery import (
    build_webhook_payload,
    deliver_webhook_event,
)

router = APIRouter(prefix="/projects", tags=["simulation-webhooks"])


def _without_secret(webhook: SimulationWebhookSubscription) -> SimulationWebhookOut:
    """Serialize a subscription without exposing its signing secret."""
    return SimulationWebhookOut.model_validate(
        SimulationWebhookOut.model_validate(webhook).model_dump(exclude={"secret"})
    )


def _get_owned_webhook(
    db: Session,
    user_id: int,
    project_id: int,
    webhook_id: int,
) -> SimulationWebhookSubscription:
    get_owned_project(db, user_id, project_id)
    webhook = (
        db.query(SimulationWebhookSubscription)
        .filter(
            SimulationWebhookSubscription.id == webhook_id,
            SimulationWebhookSubscription.project_id == project_id,
        )
        .first()
    )
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.post(
    "/{project_id}/webhooks",
    response_model=SimulationWebhookOut,
    status_code=201,
    summary="Register a simulation-completion webhook",
)
def create_simulation_webhook(
    project_id: int,
    payload: SimulationWebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookOut:
    """Create a signed webhook subscription for a project.

    The returned ``secret`` is generated once and is not recoverable from
    subsequent list calls — store it on the receiving side to verify
    ``X-TheCee-Signature`` headers.
    """
    get_owned_project(db, current_user.id, project_id)
    url_str = str(payload.url)
    if not url_str.lower().startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="webhook url must be HTTPS",
        )

    webhook = SimulationWebhookSubscription(
        project_id=project_id,
        url=url_str,
        secret=secrets.token_urlsafe(32),
        status="ACTIVE",
        event_type=payload.event_type,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return SimulationWebhookOut.model_validate(webhook)


@router.get(
    "/{project_id}/webhooks",
    response_model=SimulationWebhookListOut,
    summary="List simulation webhook subscriptions",
)
def list_simulation_webhooks(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookListOut:
    get_owned_project(db, current_user.id, project_id)
    items = (
        db.query(SimulationWebhookSubscription)
        .filter(SimulationWebhookSubscription.project_id == project_id)
        .order_by(SimulationWebhookSubscription.created_at.desc())
        .all()
    )
    return SimulationWebhookListOut(
        items=[_without_secret(item) for item in items]
    )


@router.patch(
    "/{project_id}/webhooks/{webhook_id}",
    response_model=SimulationWebhookOut,
    summary="Update a simulation webhook subscription",
)
def update_simulation_webhook(
    project_id: int,
    webhook_id: int,
    payload: SimulationWebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookOut:
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    webhook.status = payload.status
    db.commit()
    db.refresh(webhook)
    return _without_secret(webhook)


@router.delete(
    "/{project_id}/webhooks/{webhook_id}",
    summary="Delete a simulation webhook subscription",
)
def delete_simulation_webhook(
    project_id: int,
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    db.delete(webhook)
    db.commit()
    return {"ok": True}


@router.post(
    "/{project_id}/webhooks/{webhook_id}/ping",
    response_model=SimulationWebhookOut,
    summary="Send a test event to a webhook subscription",
)
def ping_simulation_webhook(
    project_id: int,
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookOut:
    """Deliver a synthetic ``simulation.ping`` event and report delivery status."""
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    payload = build_webhook_payload(
        event_type="simulation.ping",
        simulation_id=0,
        project_id=project_id,
        status="PING",
    )
    result = deliver_webhook_event(
        url=webhook.url,
        secret=webhook.secret,
        payload=payload,
        timeout_seconds=8.0,
    )
    now = datetime.now(timezone.utc)
    webhook.last_delivery_at = now
    webhook.last_delivery_status = "SUCCESS" if result["ok"] else "FAILED"
    webhook.last_delivery_error = None if result["ok"] else result.get("error")
    db.commit()
    db.refresh(webhook)
    return _without_secret(webhook)


__all__ = [
    "create_simulation_webhook",
    "list_simulation_webhooks",
    "update_simulation_webhook",
    "delete_simulation_webhook",
    "ping_simulation_webhook",
]
