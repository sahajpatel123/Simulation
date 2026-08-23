"""Pure helpers for the per-user oldest-open-item endpoint.

Composes a single "what's been sitting longest?" payload
so the dashboard can surface the age of the user's
oldest unaddressed activity (sim / decision / outcome).

The helper is pure-Python. The route layer builds a
list of activity rows (created_at, type) and hands them
to :func:`build_oldest_open_item`.

Output shape
------------
::

    {
      "oldest_age_days": int | None,
      "oldest_type": str | None,
      "oldest_project_id": int | None,
      "oldest_created_at": str | None,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import UTC, datetime

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _age_days(value: object, now: object | None = None) -> int | None:
    if value is None:
        return None
    if not hasattr(value, "timestamp"):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    ref = now if isinstance(now, datetime) else (
        datetime.now(UTC)
    )
    delta = ref - value
    return max(0, delta.days)


def build_oldest_open_item(
    activity_rows: list[tuple] | None = None,
    now: object | None = None,
) -> dict:
    """Compose the per-user oldest-open-item digest.

    Args:
        activity_rows: list of
            ``(created_at, type, project_id)`` tuples where
            ``type`` is ``sim`` / ``decision`` / ``outcome``.
        now: optional reference time (for testability).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    rows: list[tuple] = []
    for entry in activity_rows or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        created = entry[0]
        type_ = entry[1]
        project_id = entry[2] if len(entry) >= 3 else None
        rows.append((created, type_, project_id))

    if not rows:
        return {
            "oldest_age_days": None,
            "oldest_type": None,
            "oldest_project_id": None,
            "oldest_created_at": None,
            "narrative": (
                "No sims, decisions, or outcomes yet - "
                "the oldest-item tile will populate as "
                "activity accumulates."
            ),
            "key_signals": [],
        }

    # Sort by created_at ascending (oldest first).
    rows.sort(key=lambda r: r[0])
    oldest = rows[0]
    oldest_created, oldest_type, oldest_project_id = oldest
    age = _age_days(oldest_created, now=now)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if age is not None:
        if age > 30:
            severity = SIGNAL_CRITICAL
        elif age > 14:
            severity = SIGNAL_WATCH
        else:
            severity = SIGNAL_OK
        key_signals.append({
            "label": "oldest_age_days",
            "value": age,
            "severity": severity,
            "display": (
                f"Oldest item: {oldest_type} - {age} day(s) old"
            ),
        })

    # ---- Narrative ------------------------------------------------
    if age is None:
        narrative = "Oldest item: no valid created_at."
    else:
        narrative = (
            f"Oldest item is a {oldest_type} from "
            f"{age} day(s) ago."
        )

    return {
        "oldest_age_days": age,
        "oldest_type": oldest_type,
        "oldest_project_id": oldest_project_id,
        "oldest_created_at": _iso(oldest_created),
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_oldest_open_item",
]  # noqa: E501
