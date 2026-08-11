"""Pure project-wide webhook delivery health overview helpers.

The route layer already exposes per-webhook delivery health statistics
(``GET /projects/{id}/webhooks/{webhook_id}/deliveries/stats``). This module
composes those same statistics across every subscription in a project so a
founder can answer "is any of my webhook delivery broken?" in one call
instead of looping over each webhook.

The builder groups delivery rows by ``webhook_subscription_id``, delegates
the per-webhook arithmetic to :func:`build_webhook_delivery_stats` so the
project overview cannot drift from the standalone endpoint, and then rolls
the *active* subscriptions' deliveries up into one project-level health
label using the same shared rate-to-label bucketing as the per-webhook
stats. Disabled subscriptions are still listed (with their own history) but
do not drag the project verdict down, because a disabled webhook is not
expected to deliver.

The module is pure Python (no DB, no I/O): the route supplies subscription
and delivery dicts, and all arithmetic is deterministic and defensively
sanitised so one malformed legacy row can never poison the response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.simulation.webhook_delivery_stats import (
    HEALTH_NO_DATA,
    build_webhook_delivery_stats,
    health_label_for_rate,
)

STATUS_ACTIVE: str = "ACTIVE"


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {}


def _safe_text(value: Any, default: str = "") -> str:
    """Normalise a text field, falling back to ``default`` for blanks."""
    if isinstance(value, str):
        return value.strip() or default
    if value is None:
        return default
    return str(value).strip() or default


def _safe_int(value: Any, default: int = 0) -> int:
    """Parse a non-negative integer, defaulting to ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _is_active(status: Any) -> bool:
    """Return whether a subscription status is the ACTIVE enum value."""
    return _safe_text(status).upper() == STATUS_ACTIVE


def _normalise_now(now: datetime | None) -> datetime:
    """Coerce a reference timestamp to aware UTC, defaulting to now."""
    reference = now if isinstance(now, datetime) else datetime.now(UTC)
    if reference.tzinfo is None:
        return reference.replace(tzinfo=UTC)
    return reference.astimezone(UTC)


def _overall_health(total: int, success_count: int) -> str:
    """Bucket a project-wide success rate into the shared health labels."""
    rate = success_count / total if total else None
    return health_label_for_rate(total, rate)


def _overall_narrative(
    *,
    active_count: int,
    total: int,
    success_count: int,
    window_days: int,
) -> str:
    """One-line project-wide webhook delivery narrative."""
    if active_count == 0:
        return "No active webhook subscriptions - delivery health is not applicable."
    if total == 0:
        return (
            f"{active_count} active webhook(s) have no deliveries in the "
            f"last {window_days} days."
        )
    rate = success_count / total
    pct = round(rate * 100.0, 1)
    failures = total - success_count
    if rate == 1.0:
        return (
            f"All {total} deliveries across {active_count} active webhook(s) "
            f"in the last {window_days} days succeeded."
        )
    if rate >= 0.8:
        return (
            f"{failures} of {total} deliveries failed across {active_count} "
            f"active webhook(s) in the last {window_days} days "
            f"({pct}% success)."
        )
    return (
        f"Most deliveries failed across {active_count} active webhook(s) in "
        f"the last {window_days} days ({pct}% success)."
    )


def build_project_webhook_health(
    *,
    project_id: int,
    subscriptions: list[Any] | None = None,
    deliveries: list[Any] | None = None,
    window_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose a project-wide webhook delivery health payload.

    Args:
        project_id: owning project primary key (echoed back).
        subscriptions: webhook subscription rows (dict or Pydantic model).
        deliveries: delivery rows scoped to the project's subscriptions.
        window_days: how many days of delivery history to evaluate.
        now: reference timestamp for the window (defaults to now UTC).

    Returns:
        A dict matching :class:`ProjectWebhookHealthOut` with a per-webhook
        list plus a project-wide summary. Never raises: malformed rows are
        skipped or zeroed.
    """
    effective_days = max(1, _safe_int(window_days, 1))
    reference = _normalise_now(now)

    sub_rows: list[dict[str, Any]] = []
    for item in subscriptions or []:
        row = _as_dict(item)
        if row:
            sub_rows.append(row)

    delivery_rows: list[dict[str, Any]] = []
    for item in deliveries or []:
        row = _as_dict(item)
        if row:
            delivery_rows.append(row)

    deliveries_by_webhook: dict[int, list[dict[str, Any]]] = {}
    for delivery in delivery_rows:
        webhook_id = _safe_int(delivery.get("webhook_subscription_id"))
        if webhook_id <= 0:
            continue
        deliveries_by_webhook.setdefault(webhook_id, []).append(delivery)

    items: list[dict[str, Any]] = []
    sub_rows.sort(key=lambda row: _safe_int(row.get("id")))
    for subscription in sub_rows:
        webhook_id = _safe_int(subscription.get("id"))
        if webhook_id <= 0:
            continue
        stats = build_webhook_delivery_stats(
            deliveries_by_webhook.get(webhook_id),
            webhook_id=webhook_id,
            days=effective_days,
            now=reference,
        )
        items.append(
            {
                "webhook_id": webhook_id,
                "webhook_url": _safe_text(subscription.get("url")),
                "status": _safe_text(subscription.get("status"), "UNKNOWN"),
                "event_type": _safe_text(subscription.get("event_type")),
                "total_deliveries": _safe_int(stats.get("total_deliveries")),
                "success_count": _safe_int(stats.get("success_count")),
                "failed_count": _safe_int(stats.get("failed_count")),
                "success_rate": stats.get("success_rate"),
                "health_label": _safe_text(
                    stats.get("health_label"),
                    HEALTH_NO_DATA,
                ),
                "last_delivery_at": stats.get("last_delivery_at"),
                "last_delivery_status": stats.get("last_delivery_status"),
                "last_delivery_error": stats.get("last_delivery_error"),
                "narrative": _safe_text(stats.get("narrative")),
            }
        )

    active_items = [item for item in items if _is_active(item["status"])]
    total_deliveries = sum(
        item["total_deliveries"] for item in active_items
    )
    success_count = sum(item["success_count"] for item in active_items)
    failed_count = sum(item["failed_count"] for item in active_items)
    success_rate = (
        round(success_count / total_deliveries, 6)
        if total_deliveries > 0
        else None
    )

    return {
        "project_id": _safe_int(project_id),
        "generated_at": reference.isoformat(),
        "window_days": effective_days,
        "webhook_count": len(items),
        "active_webhook_count": len(active_items),
        "total_deliveries": total_deliveries,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": success_rate,
        "health_label": _overall_health(total_deliveries, success_count),
        "narrative": _overall_narrative(
            active_count=len(active_items),
            total=total_deliveries,
            success_count=success_count,
            window_days=effective_days,
        ),
        "webhooks": items,
    }


__all__ = [
    "STATUS_ACTIVE",
    "build_project_webhook_health",
]
