"""Pure helpers for the per-user last-touched-project endpoint.

Composes a single "where was I last?" payload so the
dashboard can return the user to their most recently
active project with a single click.

The helper is pure-Python. The route layer pulls the
most-recent row across (simulations, decisions,
outcomes) for the user's projects and hands the list
to :func:`build_last_touched_project`.

Output shape
------------
::

    {
      "has_activity": bool,
      "project_id": int | None,
      "project_title": str | None,
      "last_activity_at": str | None,
      "last_activity_type": str | None,   # sim / decision / outcome
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import UTC, datetime

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def build_last_touched_project(
    activity_rows: list[dict] | None = None,
) -> dict:
    """Compose the per-user last-touched-project digest.

    Args:
        activity_rows: list of dicts from the route layer.
            Each MUST expose ``project_id``,
            ``project_title``, ``activity_type``
            (``sim`` / ``decision`` / ``outcome``), and
            ``activity_at`` (datetime or ISO string).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    best: dict | None = None
    best_dt: datetime | None = None
    for entry in activity_rows or []:
        if not isinstance(entry, dict):
            continue
        raw_dt = entry.get("activity_at")
        if isinstance(raw_dt, datetime):
            dt = raw_dt
        elif isinstance(raw_dt, str):
            try:
                dt = datetime.fromisoformat(raw_dt)
            except Exception:
                continue
        else:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best = entry

    has_activity = best is not None
    project_id = best.get("project_id") if best else None
    project_title = best.get("project_title") if best else None
    last_activity_type = (
        best.get("activity_type") if best else None
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "has_activity",
        "value": has_activity,
        "severity": (
            SIGNAL_OK if has_activity else SIGNAL_WATCH
        ),
        "display": (
            f"Last touched: {project_title}"
            if has_activity
            else "No activity yet"
        ),
    })

    # ---- Narrative ------------------------------------------------
    if not has_activity:
        narrative = (
            "No project activity yet - start a simulation, "
            "decision, or outcome to populate this tile."
        )
    else:
        narrative = (
            f"Last touched project: '{project_title}' "
            f"({last_activity_type})."
        )

    return {
        "has_activity": has_activity,
        "project_id": project_id,
        "project_title": project_title,
        "last_activity_at": _iso(best_dt) if has_activity else None,
        "last_activity_type": last_activity_type,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_last_touched_project",
]  # noqa: E501
