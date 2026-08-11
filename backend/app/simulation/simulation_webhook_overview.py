"""Pure per-simulation webhook delivery overview helpers.

The route layer in ``app/api/v1/simulation_webhooks.py`` loads a project's
webhook subscriptions and a simulation's delivery attempts, then hands JSON
dicts to :func:`build_simulation_webhook_delivery_overview` so the response
is deterministic and testable without PostgreSQL.

The overview groups every delivery attempt under the subscription that sent
it, ordered newest-first in both dimensions, and reports how many webhooks
were considered plus how many delivery attempts exist. Deliveries whose
``webhook_subscription_id`` does not match any loaded subscription are
ignored, so a malformed legacy row or cross-project reference can never leak
into another user's response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {}


def _safe_int(value: Any, default: int = 0) -> int:
    """Parse a non-negative integer, defaulting to 0 for unusable values."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed >= 0 else default


def _safe_text(value: Any, default: str = "") -> str:
    """Normalise a text field, falling back to ``default`` for blanks."""
    if isinstance(value, str):
        return value.strip() or default
    if value is None:
        return default
    return str(value).strip() or default


def _sort_key(row: dict[str, Any]) -> tuple[datetime, int]:
    """Newest-first key using ``created_at`` then ``id``."""
    created = row.get("created_at")
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        else:
            created = created.astimezone(UTC)
    elif created is not None:
        try:
            parsed = datetime.fromisoformat(str(created))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            created = parsed.astimezone(UTC)
        except (TypeError, ValueError):
            created = datetime.min.replace(tzinfo=UTC)
    else:
        created = datetime.min.replace(tzinfo=UTC)
    return created, _safe_int(row.get("id"))


def build_simulation_webhook_delivery_overview(
    *,
    project_id: int,
    simulation_id: int,
    subscriptions: list[Any] | None = None,
    deliveries: list[Any] | None = None,
) -> dict[str, Any]:
    """Group webhook delivery attempts under their subscription.

    ``subscriptions`` are webhook rows (dict or Pydantic model) scoped to the
    project; ``deliveries`` are delivery rows scoped to the simulation.
    Deliveries are grouped by ``webhook_subscription_id``; rows without a
    matching loaded subscription are dropped. Both lists are sorted
    newest-first by ``created_at`` then ``id`` so the overview matches the
    delivery-history and export endpoints.
    """
    sub_rows = [_as_dict(item) for item in (subscriptions or []) if _as_dict(item)]
    delivery_rows = [
        _as_dict(item) for item in (deliveries or []) if _as_dict(item)
    ]
    sub_rows.sort(key=_sort_key, reverse=True)
    delivery_rows.sort(key=_sort_key, reverse=True)

    deliveries_by_webhook: dict[int, list[dict[str, Any]]] = {}
    for delivery in delivery_rows:
        webhook_id = _safe_int(delivery.get("webhook_subscription_id"))
        if webhook_id <= 0:
            continue
        deliveries_by_webhook.setdefault(webhook_id, []).append(delivery)

    items: list[dict[str, Any]] = []
    delivery_count = 0
    for subscription in sub_rows:
        webhook_id = _safe_int(subscription.get("id"))
        if webhook_id <= 0:
            continue
        grouped = deliveries_by_webhook.get(webhook_id, [])
        delivery_count += len(grouped)
        items.append(
            {
                "webhook_id": webhook_id,
                "webhook_url": _safe_text(subscription.get("url")),
                "webhook_status": _safe_text(
                    subscription.get("status"),
                    default="UNKNOWN",
                ),
                "webhook_event_type": _safe_text(
                    subscription.get("event_type")
                ),
                "deliveries": grouped,
            }
        )

    return {
        "project_id": _safe_int(project_id),
        "simulation_id": _safe_int(simulation_id),
        "webhook_count": len(items),
        "delivery_count": delivery_count,
        "items": items,
    }


__all__ = ["build_simulation_webhook_delivery_overview"]
