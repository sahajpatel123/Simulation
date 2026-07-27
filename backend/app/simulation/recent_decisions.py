"""Pure helpers for the per-user recent-decisions endpoint.

Composes a small 'what did you decide recently?' payload:
the last 5 decisions across the user's projects, suitable
for a dashboard widget.

The helper is pure-Python. The route layer passes a
list of recent decision dicts (sorted by created_at
descending) and hands them to
:func:`build_recent_decisions`.

Output shape
------------
::

    {
      "decisions": list[dict],
      "decision_count": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

MAX_RECENT: int = 5

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


def build_recent_decisions(
    recent_decision_dicts: list[dict] | None = None,
) -> dict:
    """Compose the per-user recent-decisions digest.

    Args:
        recent_decision_dicts: list of decision dicts from
            the route layer. Each must expose
            ``decision_id`` (or ``id``), ``project_id``,
            ``title``, ``status``, and ``created_at``.
            The list is assumed to be already sorted by
            created_at descending.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    recent = []
    for entry in recent_decision_dicts or []:
        if not isinstance(entry, dict):
            continue
        decision_id = (
            entry.get("decision_id") or entry.get("id")
        )
        project_id = entry.get("project_id")
        title = entry.get("title")
        status = entry.get("status")
        created_at = entry.get("created_at")
        recent.append({
            "decision_id": decision_id,
            "project_id": project_id,
            "title": title or "",
            "status": status or "UNKNOWN",
            "created_at": _iso(created_at),
        })
    recent = recent[:MAX_RECENT]
    decision_count = len(recent)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if decision_count > 0:
        # Worst is the entry with status PENDING
        # (decisions that haven't been resolved yet).
        pending_count = sum(
            1 for d in recent if d["status"] == "PENDING"
        )
        key_signals.append({
            "label": "recent_decision_count",
            "value": decision_count,
            "severity": (
                SIGNAL_OK
                if pending_count == 0
                else SIGNAL_WATCH
                if pending_count <= 1
                else SIGNAL_CRITICAL
            ),
            "display": f"Recent decisions: {decision_count}",
        })

    # ---- Narrative ------------------------------------------------
    if decision_count == 0:
        narrative = (
            "No recent decisions yet - run a few "
            "decisions to populate this tile."
        )
    else:
        pending = sum(
            1 for d in recent if d["status"] == "PENDING"
        )
        if pending == 0:
            narrative = (
                f"Last {decision_count} decision(s): all "
                f"resolved."
            )
        else:
            narrative = (
                f"Last {decision_count} decision(s): "
                f"{pending} pending."
            )

    return {
        "decisions": recent,
        "decision_count": decision_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_RECENT",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_recent_decisions",
]  # noqa: E501

