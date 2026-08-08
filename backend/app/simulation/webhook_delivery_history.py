"""Persistence and manual-retry helpers for simulation webhook deliveries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.simulation_webhook_delivery import SimulationWebhookDelivery
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.simulation.simulation_webhook_delivery import (
    build_webhook_payload,
    deliver_webhook_event,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_webhook_delivery(
    db: Session,
    *,
    subscription: SimulationWebhookSubscription,
    simulation_id: int | None,
    event_type: str,
    status: str,
    conversion_rate: float | None,
    error: str | None,
    result: dict[str, Any],
    payload: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> SimulationWebhookDelivery:
    """Persist one delivery attempt and refresh the subscription's last status.

    Deliberately runs before a Celery retry is re-raised so the attempt is
    committed even if the task fails again. The request body is stored as a
    JSON object so the history is useful for debugging without needing the
    signing secret.
    """
    now = _utcnow()
    ok = bool(result.get("ok"))
    delivery = SimulationWebhookDelivery(
        webhook_subscription_id=subscription.id,
        simulation_id=simulation_id,
        event_type=event_type,
        status="SUCCESS" if ok else "FAILED",
        http_status=result.get("status_code"),
        error=None if ok else (result.get("error") or "unknown delivery error"),
        conversion_rate=conversion_rate,
        request_body=payload,
        retry_count=int(retry_count),
        delivered_at=now,
    )
    db.add(delivery)

    subscription.last_delivery_at = now
    subscription.last_delivery_status = "SUCCESS" if ok else "FAILED"
    subscription.last_delivery_error = None if ok else delivery.error
    db.commit()
    db.refresh(delivery)
    return delivery


def retry_failed_delivery(
    db: Session,
    *,
    delivery: SimulationWebhookDelivery,
) -> SimulationWebhookDelivery:
    """Re-deliver a recorded failed delivery as a new attempt.

    Reconstructs the event payload from the durable history row instead of
    replaying stored JSON, then records the retry attempt with an incremented
    retry count. The caller is responsible for ownership/active checks.
    """
    event_status = (
        "COMPLETED"
        if delivery.event_type.endswith("completed")
        else "FAILED"
    )
    payload = build_webhook_payload(
        event_type=delivery.event_type,
        simulation_id=delivery.simulation_id or 0,
        project_id=delivery.subscription.project_id,
        status=event_status,
        conversion_rate=delivery.conversion_rate,
        error=None if event_status == "COMPLETED" else delivery.error,
    )
    result = deliver_webhook_event(
        url=delivery.subscription.url,
        secret=delivery.subscription.secret,
        payload=payload,
    )
    return record_webhook_delivery(
        db,
        subscription=delivery.subscription,
        simulation_id=delivery.simulation_id,
        event_type=delivery.event_type,
        status=event_status,
        conversion_rate=delivery.conversion_rate,
        error=delivery.error,
        result=result,
        payload=payload,
        retry_count=int(delivery.retry_count) + 1,
    )


__all__ = [
    "record_webhook_delivery",
    "retry_failed_delivery",
]
