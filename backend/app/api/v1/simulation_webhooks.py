"""CRUD + ping API for simulation-completion webhook subscriptions."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.models.simulation_webhook_delivery import SimulationWebhookDelivery
from app.models.user import User
from app.schemas.simulation_webhook_delivery import (
    SimulationWebhookDeliveryListOut,
    SimulationWebhookDeliveryOut,
    SimulationWebhookRetryOut,
)
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
from app.simulation.webhook_delivery_history import (
    record_webhook_delivery,
    retry_failed_delivery,
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


def _get_owned_delivery(
    db: Session,
    user_id: int,
    project_id: int,
    webhook_id: int,
    delivery_id: int,
) -> SimulationWebhookDelivery:
    webhook = _get_owned_webhook(db, user_id, project_id, webhook_id)
    delivery = (
        db.query(SimulationWebhookDelivery)
        .filter(
            SimulationWebhookDelivery.id == delivery_id,
            SimulationWebhookDelivery.webhook_subscription_id == webhook.id,
        )
        .first()
    )
    if not delivery:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    return delivery


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
    record_webhook_delivery(
        db,
        subscription=webhook,
        simulation_id=None,
        event_type=payload["event"],
        attempt_status="PING",
        conversion_rate=None,
        error=None,
        result=result,
        payload=payload,
    )
    db.refresh(webhook)
    return _without_secret(webhook)


@router.get(
    "/{project_id}/webhooks/{webhook_id}/deliveries",
    response_model=SimulationWebhookDeliveryListOut,
    summary="List simulation webhook delivery history",
)
def list_simulation_webhook_deliveries(
    project_id: int,
    webhook_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookDeliveryListOut:
    """Return recent delivery attempts for one webhook, newest first."""
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    items = (
        db.query(SimulationWebhookDelivery)
        .filter(
            SimulationWebhookDelivery.webhook_subscription_id == webhook.id,
        )
        .order_by(
            SimulationWebhookDelivery.created_at.desc(),
            SimulationWebhookDelivery.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return SimulationWebhookDeliveryListOut(
        items=[SimulationWebhookDeliveryOut.model_validate(item) for item in items]
    )


@router.post(
    "/{project_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/retry",
    response_model=SimulationWebhookRetryOut,
    summary="Retry a failed simulation webhook delivery",
)
def retry_simulation_webhook_delivery(
    project_id: int,
    webhook_id: int,
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookRetryOut:
    """Re-deliver a failed webhook event and record a new delivery attempt."""
    delivery = _get_owned_delivery(
        db,
        current_user.id,
        project_id,
        webhook_id,
        delivery_id,
    )
    if delivery.status == "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail="Only failed deliveries can be retried",
        )
    if delivery.subscription.status != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail="Webhook subscription must be ACTIVE to retry",
        )
    new_delivery = retry_failed_delivery(db, delivery=delivery)
    return SimulationWebhookRetryOut(
        delivery=SimulationWebhookDeliveryOut.model_validate(new_delivery)
    )


__all__ = [
    "create_simulation_webhook",
    "list_simulation_webhooks",
    "update_simulation_webhook",
    "delete_simulation_webhook",
    "ping_simulation_webhook",
    "list_simulation_webhook_deliveries",
    "retry_simulation_webhook_delivery",
]
