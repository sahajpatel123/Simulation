"""Windowed delivery-health statistics for simulation webhooks.

The route layer in ``app/api/v1/simulation_webhooks.py`` already lists raw
delivery attempts and exports them. This module turns a window of delivery
rows into an at-a-glance health summary: success/failure counts, HTTP status
and event-type distributions, retry pressure, the most frequent delivery
errors, and a simple HEALTHY/DEGRADED/DOWN verdict. Keeping the aggregation
pure makes it easy to unit-test and reuse for dashboards or future exports.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

HEALTH_NO_DATA = "NO_DATA"
HEALTH_HEALTHY = "HEALTHY"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_DOWN = "DOWN"
MAX_TOP_ERRORS = 5


def _parse_datetime(raw: Any) -> datetime | None:
    """Parse a delivery timestamp into a UTC-aware ``datetime``."""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_str(raw: Any, *, default: str = "") -> str:
    """Normalise a text field, falling back to ``default`` for blanks."""
    if isinstance(raw, str):
        return raw.strip() or default
    if raw is None:
        return default
    return str(raw).strip() or default


def _safe_int(raw: Any) -> int:
    """Parse a non-negative integer, defaulting to 0 for unusable values."""
    if raw is None or isinstance(raw, bool):
        return 0
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed >= 0 else 0


def _http_status_key(raw: Any) -> str | None:
    """Normalise a plausible HTTP status code, or ``None`` if unusable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        code = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if 100 <= code <= 599:
        return str(code)
    return None


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    """Render a counter with deterministic ordering (count desc, key asc)."""
    return {
        key: counter[key]
        for key in sorted(counter, key=lambda item: (-counter[item], item))
    }


def _health_label(total: int, success_rate: float | None) -> str:
    if total == 0:
        return HEALTH_NO_DATA
    if success_rate is None:
        return HEALTH_DOWN
    if success_rate == 1.0:
        return HEALTH_HEALTHY
    if success_rate >= 0.8:
        return HEALTH_DEGRADED
    return HEALTH_DOWN


def _narrative(
    *,
    total: int,
    failed_count: int,
    success_rate: float | None,
    days: int,
) -> str:
    if total == 0:
        return f"No webhook deliveries recorded in the last {days} days."
    rate = success_rate if success_rate is not None else 0.0
    pct = round(rate * 100, 1)
    failures = failed_count
    if rate == 1.0:
        return f"All {total} deliveries in the last {days} days succeeded."
    if rate >= 0.8:
        return (
            f"{failures} of {total} deliveries failed in the last {days} "
            f"days ({pct}% success)."
        )
    return (
        f"Most deliveries failed in the last {days} days "
        f"({pct}% success)."
    )


def build_webhook_delivery_stats(
    rows: list[dict[str, Any]] | None,
    *,
    webhook_id: int,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate a window of webhook delivery rows into a health summary.

    Rows are expected to be JSON-friendly dicts (as produced by
    ``SimulationWebhookDeliveryOut.model_dump(mode="json")``). Rows without a
    parseable ``created_at`` (falling back to ``delivered_at``) are skipped
    because their position in the window cannot be established.
    """
    window_days = max(1, _safe_int(days))
    reference = now if isinstance(now, datetime) else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    else:
        reference = reference.astimezone(UTC)
    cutoff = reference - timedelta(days=window_days)

    items: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        created = _parse_datetime(
            row.get("created_at") or row.get("delivered_at")
        )
        if created is None or created < cutoff:
            continue
        items.append((created, row))

    total = len(items)
    status_counts: Counter[str] = Counter()
    http_status_counts: Counter[str] = Counter()
    event_type_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    success_count = 0
    failed_count = 0
    retry_total = 0
    max_retry_count = 0

    for _, row in items:
        status = _safe_str(row.get("status"), default="UNKNOWN")
        status_counts[status] += 1
        if status == "SUCCESS":
            success_count += 1
        elif status == "FAILED":
            failed_count += 1

        http_status = _http_status_key(row.get("http_status"))
        if http_status is not None:
            http_status_counts[http_status] += 1

        event_type_counts[
            _safe_str(row.get("event_type"), default="UNKNOWN")
        ] += 1

        retry_count = _safe_int(row.get("retry_count"))
        retry_total += retry_count
        max_retry_count = max(max_retry_count, retry_count)

        # A SUCCESS delivery may still carry a simulation error for
        # ``simulation.failed`` events; only FAILED deliveries count as
        # delivery errors so a healthy endpoint never looks broken.
        error = _safe_str(row.get("error")) if status == "FAILED" else ""
        if error:
            error_counts[error] += 1

    success_rate = round(success_count / total, 6) if total else None
    ordered = sorted(
        items,
        key=lambda item: (item[0], _safe_int(item[1].get("id"))),
    )
    first = ordered[0] if ordered else None
    last = ordered[-1] if ordered else None
    last_delivery_status: str | None = None
    last_delivery_error: str | None = None
    if last is not None:
        last_delivery_status = _safe_str(last[1].get("status")) or None
        if last_delivery_status == "FAILED":
            last_delivery_error = _safe_str(last[1].get("error")) or None

    return {
        "webhook_id": webhook_id,
        "window_days": window_days,
        "total_deliveries": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": success_rate,
        "status_breakdown": _sorted_counts(status_counts),
        "http_status_breakdown": _sorted_counts(http_status_counts),
        "event_type_breakdown": _sorted_counts(event_type_counts),
        "retry_count_total": retry_total,
        "max_retry_count": max_retry_count,
        "top_errors": [
            {"error": text, "count": count}
            for text, count in sorted(
                error_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:MAX_TOP_ERRORS]
        ],
        "first_delivery_at": first[0] if first else None,
        "last_delivery_at": last[0] if last else None,
        "last_delivery_status": last_delivery_status,
        "last_delivery_error": last_delivery_error,
        "health_label": _health_label(total, success_rate),
        "narrative": _narrative(
            total=total,
            failed_count=failed_count,
            success_rate=success_rate,
            days=window_days,
        ),
    }


__all__ = [
    "HEALTH_DEGRADED",
    "HEALTH_DOWN",
    "HEALTH_HEALTHY",
    "HEALTH_NO_DATA",
    "MAX_TOP_ERRORS",
    "build_webhook_delivery_stats",
]
