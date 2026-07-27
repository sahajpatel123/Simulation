"""Pure helpers for the per-user digest snapshot endpoint.

A "snapshot" captures every user-level digest into one
payload so the founder (or the system) can archive it for
later comparison, or send it as a single email.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls each source digest (or recomputes it) and
hands the dicts to :func:`build_digest_snapshot`.

Output shape
------------
::

    {
      "snapshot_at": "ISO timestamp",
      "schema_version": 1,
      "dashboard": {...},
      "account_health": {...},
      "coverage_gaps": {...},
      "notifications": {...},
      "weekly_digest": {...},
    }
"""
from __future__ import annotations

from datetime import datetime, timezone


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def build_digest_snapshot(
    dashboard: dict | None,
    account_health: dict | None,
    coverage_gaps: dict | None,
    notifications: dict | None,
    weekly_digest: dict | None,
    now: object | None = None,
) -> dict:
    """Compose the per-user digest snapshot.

    Args:
        dashboard: output of
            :func:`app.simulation.user_dashboard.build_user_dashboard`.
        account_health: output of
            :func:`app.simulation.account_health.build_account_health`.
        coverage_gaps: output of
            :func:`app.simulation.coverage_gaps.build_coverage_gaps`.
        notifications: output of
            :func:`app.simulation.notifications.build_notifications`.
        weekly_digest: output of
            :func:`app.simulation.weekly_digest.build_weekly_digest`.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    snapshot_at = (
        now if isinstance(now, datetime) else (
            datetime.now(timezone.utc)
        )
    )
    iso = (
        snapshot_at.isoformat()
        if hasattr(snapshot_at, "isoformat") else str(snapshot_at)
    )

    return {
        "snapshot_at": iso,
        "schema_version": 1,
        "dashboard": dashboard or {},
        "account_health": account_health or {},
        "coverage_gaps": coverage_gaps or {},
        "notifications": notifications or {},
        "weekly_digest": weekly_digest or {},
    }


__all__ = [
    "build_digest_snapshot",
]  # noqa: E501