"""Persistence and manual-retry helpers for simulation webhook deliveries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.simulation_webhook_delivery import SimulationWebhookDelivery
from app.models.simulation_webhook_subscription import SimulationWebhookSubscription
from app.simulation.simulation_webhook_delivery import (
    build_webhook_payload,
    deliver_webhook_event,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _default_attempt_status(event_type: str) -> str:
    """Best-effort status fallback for rows written before attempt_status existed."""
    return "COMPLETED" if event_type.endswith("completed") else "FAILED"


def _event_key(delivery: SimulationWebhookDelivery) -> tuple[int | None, str]:
    """Identity of the logical event a delivery row represents."""
    return (delivery.simulation_id, delivery.event_type)


def record_webhook_delivery(
    db: Session,
    *,
    subscription: SimulationWebhookSubscription,
    simulation_id: int | None,
    event_type: str,
    attempt_status: str | None,
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
    is_failed_event = attempt_status not in (None, "COMPLETED", "PING")
    # ``error`` means the delivery/transport error for successful events, but
    # for failed events it is the simulation error the event carries
    # (delivery status is tracked separately). This keeps manual retries
    # faithful even when the retry itself succeeds.
    delivery_error = (
        error
        if is_failed_event
        else (None if ok else (result.get("error") or "unknown delivery error"))
    )
    delivery = SimulationWebhookDelivery(
        webhook_subscription_id=subscription.id,
        simulation_id=simulation_id,
        event_type=event_type,
        attempt_status=attempt_status,
        status="SUCCESS" if ok else "FAILED",
        http_status=result.get("status_code"),
        error=delivery_error,
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
    if delivery.status != "FAILED":
        raise ValueError(
            f"cannot retry delivery with status {delivery.status!r}; "
            "only failed deliveries are retryable"
        )
    if delivery.subscription.status != "ACTIVE":
        raise ValueError(
            "cannot retry delivery on a disabled webhook subscription"
        )

    event_status = delivery.attempt_status or _default_attempt_status(
        delivery.event_type
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
        attempt_status=event_status,
        conversion_rate=delivery.conversion_rate,
        error=delivery.error,
        result=result,
        payload=payload,
        retry_count=int(delivery.retry_count) + 1,
    )


def retry_failed_deliveries(
    db: Session,
    *,
    subscription: SimulationWebhookSubscription,
    limit: int = 25,
) -> dict[str, Any]:
    """Re-deliver up to ``limit`` still-outstanding failed deliveries.

    One call replays the whole backlog after an endpoint outage instead of
    forcing one retry request per delivery. Failed rows that already have a
    later successful delivery for the same event are skipped, and once a
    retry succeeds for an event the older failed rows for that event are not
    replayed, so repeated calls cannot duplicate notifications. Every attempt
    is persisted as a new delivery row (each with its own commit so a later
    failure never loses earlier attempts), and the returned summary reports
    how many retries succeeded, how many rows were skipped, and which
    attempts still failed.
    """
    if subscription.status != "ACTIVE":
        raise ValueError(
            "cannot retry failed deliveries on a disabled webhook subscription"
        )

    failed_deliveries = (
        db.query(SimulationWebhookDelivery)
        .filter(
            SimulationWebhookDelivery.webhook_subscription_id == subscription.id,
            SimulationWebhookDelivery.status == "FAILED",
        )
        .order_by(
            SimulationWebhookDelivery.created_at.desc(),
            SimulationWebhookDelivery.id.desc(),
        )
        .limit(limit)
        .all()
    )
    if not failed_deliveries:
        return {
            "requested": 0,
            "retried": 0,
            "skipped": 0,
            "succeeded": 0,
            "failed": 0,
            "failed_delivery_ids": [],
            "deliveries": [],
        }

    # Original FAILED rows are kept as audit history, so a successful manual
    # retry leaves them behind. Skip any failed row that already has a later
    # SUCCESS for the same logical event, otherwise a second bulk-retry call
    # would replay the same notifications.
    min_failed_id = min(delivery.id for delivery in failed_deliveries)
    later_successes = (
        db.query(SimulationWebhookDelivery)
        .filter(
            SimulationWebhookDelivery.webhook_subscription_id == subscription.id,
            SimulationWebhookDelivery.status == "SUCCESS",
            SimulationWebhookDelivery.id > min_failed_id,
        )
        .all()
    )
    latest_success_id: dict[tuple[int | None, str], int] = {}
    for success in later_successes:
        key = _event_key(success)
        latest_success_id[key] = max(
            latest_success_id.get(key, success.id),
            success.id,
        )

    retried: list[SimulationWebhookDelivery] = []
    succeeded_this_run: set[tuple[int | None, str]] = set()
    for delivery in failed_deliveries:
        key = _event_key(delivery)
        if key in succeeded_this_run:
            continue
        if latest_success_id.get(key, -1) > delivery.id:
            continue
        new_delivery = retry_failed_delivery(db, delivery=delivery)
        retried.append(new_delivery)
        if new_delivery.status == "SUCCESS":
            succeeded_this_run.add(key)

    succeeded = sum(1 for item in retried if item.status == "SUCCESS")
    return {
        "requested": len(failed_deliveries),
        "retried": len(retried),
        "skipped": len(failed_deliveries) - len(retried),
        "succeeded": succeeded,
        "failed": len(retried) - succeeded,
        "failed_delivery_ids": [
            item.id for item in retried if item.status != "SUCCESS"
        ],
        "deliveries": retried,
    }


__all__ = [
    "record_webhook_delivery",
    "retry_failed_delivery",
    "retry_failed_deliveries",
]
