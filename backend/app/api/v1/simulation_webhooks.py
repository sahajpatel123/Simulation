"""CRUD + ping API for simulation-completion webhook subscriptions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.models.simulation_webhook_delivery import SimulationWebhookDelivery
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.models.user import User
from app.schemas.simulation_webhook_delivery import (
    SimulationWebhookBatchRetryOut,
    SimulationWebhookDeliveryListOut,
    SimulationWebhookDeliveryOut,
    SimulationWebhookDeliveryStatsOut,
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
    generate_webhook_secret,
    rotate_webhook_secret,
)
from app.simulation.webhook_delivery_history import (
    record_webhook_delivery,
    retry_failed_deliveries,
    retry_failed_delivery,
)
from app.simulation.webhook_delivery_history_export import (
    webhook_deliveries_to_csv,
    webhook_deliveries_to_json,
)
from app.simulation.webhook_delivery_stats import build_webhook_delivery_stats

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
        secret=generate_webhook_secret(),
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
    summary="Update a simulation webhook subscription (status, URL, or event type)",
)
def update_simulation_webhook(
    project_id: int,
    webhook_id: int,
    payload: SimulationWebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookOut:
    """Update a simulation webhook subscription without losing its history.

    ``status`` is always applied (defaults to ``ACTIVE`` for backward
    compatibility with the original update contract). ``url`` and
    ``event_type`` are applied only when provided, which lets a founder
    retarget an existing subscription — for example moving from a staging
    endpoint to production — while preserving the delivery audit trail and
    keeping the same HMAC signing secret. The secret is never returned here
    (same as list), so receivers must already hold it; rotation remains a
    separate, explicit endpoint.
    """
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    if payload.url is not None:
        webhook.url = payload.url
    if payload.event_type is not None:
        webhook.event_type = payload.event_type
    webhook.status = payload.status
    db.commit()
    db.refresh(webhook)
    return _without_secret(webhook)


@router.post(
    "/{project_id}/webhooks/{webhook_id}/rotate-secret",
    response_model=SimulationWebhookOut,
    summary="Rotate the signing secret for a simulation webhook",
    # Rotation invalidates the receiver's current key, so cap automated
    # callers from churning secrets (and deliveries) in a tight loop.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def rotate_simulation_webhook_secret(
    project_id: int,
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookOut:
    """Generate a new HMAC signing secret for a webhook subscription.

    The new secret is returned exactly once; list and update responses hide
    it, so the receiving endpoint must store it immediately. Delivery
    history and subscription settings (URL, event type, status) are
    preserved, which makes rotation the safe way to invalidate a leaked or
    compromised secret. The endpoint guarantees the new secret differs from
    the current one; if a distinct secret cannot be generated it fails
    without committing a no-op rotation.
    """
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    try:
        webhook.secret = rotate_webhook_secret(webhook.secret)
    except RuntimeError as exc:
        # Never commit a "rotation" that kept the old key: the receiver
        # would believe the leaked secret was invalidated when it was not.
        raise HTTPException(
            status_code=500,
            detail="Could not rotate webhook secret; please try again",
        ) from exc
    db.commit()
    db.refresh(webhook)
    return SimulationWebhookOut.model_validate(webhook)


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


@router.get(
    "/{project_id}/webhooks/{webhook_id}/deliveries/export",
    response_class=StreamingResponse,
    summary=(
        "Export simulation webhook delivery history as CSV "
        "(or JSON with ?format=json)"
    ),
    # Export can scan up to 5000 delivery rows; cap polling so a stray
    # dashboard loop can't drive repeated per-webhook history scans.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_simulation_webhook_deliveries(
    project_id: int,
    webhook_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns the "
            "spreadsheet-friendly table; ``json`` returns the "
            "raw delivery rows. Unsupported values return a 400 response."
        ),
    ),
    limit: int = Query(
        default=1000,
        ge=1,
        le=5000,
        description="Maximum number of delivery attempts to export.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Spreadsheet export of a webhook's delivery audit trail, newest first."""
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    rows = (
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
    items = [
        SimulationWebhookDeliveryOut.model_validate(row).model_dump(mode="json")
        for row in rows
    ]

    metadata = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "webhook_id": webhook_id,
        "limit": limit,
        "total": len(items),
        "format_version": "1",
    }

    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported export format {format!r}; expected 'csv' or 'json'",
        )
    if fmt == "json":
        body = webhook_deliveries_to_json(items, metadata=metadata).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="webhook-deliveries.json"'
                ),
                "Content-Length": str(len(body)),
            },
        )

    body = webhook_deliveries_to_csv(items, metadata=metadata).encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="webhook-deliveries.csv"',
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{project_id}/webhooks/{webhook_id}/deliveries/stats",
    response_model=SimulationWebhookDeliveryStatsOut,
    summary="Show delivery health statistics for a simulation webhook",
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def get_simulation_webhook_delivery_stats(
    project_id: int,
    webhook_id: int,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookDeliveryStatsOut:
    """Return a windowed health summary for one webhook subscription.

    Aggregates delivery attempts in the last ``days`` days (default 30):
    success/failure counts and rate, HTTP status and event-type breakdowns,
    retry pressure, the most frequent delivery errors, and a
    HEALTHY/DEGRADED/DOWN verdict so operators can spot an endpoint outage
    without scanning the raw delivery list.
    """
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    rows = (
        db.query(SimulationWebhookDelivery)
        .filter(
            SimulationWebhookDelivery.webhook_subscription_id == webhook.id,
            SimulationWebhookDelivery.created_at >= cutoff,
        )
        .order_by(
            SimulationWebhookDelivery.created_at.desc(),
            SimulationWebhookDelivery.id.desc(),
        )
        .all()
    )
    items = [
        SimulationWebhookDeliveryOut.model_validate(row).model_dump(mode="json")
        for row in rows
    ]
    stats = build_webhook_delivery_stats(
        items,
        webhook_id=webhook.id,
        days=days,
        now=now,
    )
    return SimulationWebhookDeliveryStatsOut(**stats)


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


@router.post(
    "/{project_id}/webhooks/{webhook_id}/retry-failed",
    response_model=SimulationWebhookBatchRetryOut,
    summary="Retry all failed deliveries for a webhook subscription",
    # Bulk retry fans out real HTTP requests per delivery; cap polling so a
    # stray dashboard loop cannot drive repeated backlog replays.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def retry_failed_simulation_webhook_deliveries(
    project_id: int,
    webhook_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationWebhookBatchRetryOut:
    """Re-deliver every outstanding failed event for one webhook, newest first.

    Useful after an endpoint outage: one call replays the backlog instead of
    one retry request per delivery. Failed rows that already have a later
    successful delivery for the same event are skipped, so repeated calls do
    not duplicate notifications. Each attempt is recorded as a new delivery
    row; the summary reports how many attempts succeeded, how many rows were
    skipped, and which deliveries still failed.
    """
    webhook = _get_owned_webhook(db, current_user.id, project_id, webhook_id)
    if webhook.status != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail="Webhook subscription must be ACTIVE to retry",
        )
    result = retry_failed_deliveries(db, subscription=webhook, limit=limit)
    return SimulationWebhookBatchRetryOut(
        requested=result["requested"],
        retried=result["retried"],
        skipped=result["skipped"],
        succeeded=result["succeeded"],
        failed=result["failed"],
        failed_delivery_ids=result["failed_delivery_ids"],
        deliveries=[
            SimulationWebhookDeliveryOut.model_validate(item)
            for item in result["deliveries"]
        ],
    )


__all__ = [
    "create_simulation_webhook",
    "list_simulation_webhooks",
    "update_simulation_webhook",
    "rotate_simulation_webhook_secret",
    "delete_simulation_webhook",
    "ping_simulation_webhook",
    "list_simulation_webhook_deliveries",
    "export_simulation_webhook_deliveries",
    "get_simulation_webhook_delivery_stats",
    "retry_simulation_webhook_delivery",
    "retry_failed_simulation_webhook_deliveries",
]
