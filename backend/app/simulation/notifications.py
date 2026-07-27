"""Pure helpers for the per-user notifications digest.

Composes a chronological list of items that would
trigger an inbox / push notification so the dashboard
can render an "inbox" view without fanning out to
multiple endpoints.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the source data and hands it to
:func:`build_notifications`.

Output shape
------------
::

    {
      "notification_count": int,
      "notifications": list[dict],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import datetime, timezone

MAX_NOTIFICATIONS: int = 25

NOTIFICATION_CRITICAL: str = "critical"
NOTIFICATION_WATCH: str = "watch"
NOTIFICATION_INFO: str = "info"


def _iso(value: object) -> str:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _classify_severity(category: str) -> str:
    """Map notification category to severity bucket."""
    if category in {"blindspot", "intervention_quickwin"}:
        return NOTIFICATION_CRITICAL
    if category in {"pending_decision", "intervention", "premortem_critical"}:
        return NOTIFICATION_WATCH
    return NOTIFICATION_INFO


def _ensure_dt(value: object) -> datetime:
    """Coerce a datetime-or-string value into a datetime for
    sorting. Falls back to the unix epoch when the input
    isn't recognisable so the item still shows up at the
    top of the feed (defensive default)."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def build_notifications(
    blindspots: list[dict] | None = None,
    intervention_dicts: list[dict] | None = None,
    pending_decisions: list[dict] | None = None,
    recent_premortem_criticals: int = 0,
    now: object | None = None,
) -> dict:
    """Compose the per-user notifications digest.

    Args:
        blindspots: list of ``user_market_blindspots``
            rows (``blindspot_type``, ``blindspot_value``,
            ``occurrence_count``, ``last_surfaced_to_user``).
        intervention_dicts: list of intervention rows
            from ``build_intervention_digest`` or the
            intervention-generator output (must include
            ``difficulty`` and ``priority_score`` for
            quick-win classification).
        pending_decisions: list of pending-decision rows
            (``id``, ``title``, ``created_at``).
        recent_premortem_criticals: count of CRITICAL
            premortem failure modes across the user's
            projects in the recent window.
        now: optional reference time for narrative.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    notifications: list[dict] = []

    # ---- Blindspots ------------------------------------------------
    for b in blindspots or []:
        if not isinstance(b, dict):
            continue
        notifications.append({
            "category": "blindspot",
            "title": (
                f"{b.get('blindspot_type', 'Pattern')} "
                f"recurring"
            ),
            "summary": (
                b.get("blindspot_value", "")
            ),
            "severity": NOTIFICATION_CRITICAL,
            "occurred_at": _iso(
                b.get("last_surfaced_to_user")
                or b.get("first_seen"),
            ),
            "ref_kind": "blindspot",
            "ref_id": None,
            "ref_label": b.get("blindspot_type"),
        })

    # ---- Intervention quick wins ----------------------------------
    for iv in intervention_dicts or []:
        if not isinstance(iv, dict):
            continue
        is_quick_win = (
            (iv.get("difficulty") or "").upper() == "LOW"
            and (
                isinstance(iv.get("priority_score"), (int, float))
                and float(iv.get("priority_score")) > 0.70
            )
        )
        if not is_quick_win:
            continue
        notifications.append({
            "category": "intervention_quickwin",
            "title": (
                f"Quick win: {iv.get('title') or 'TBD'}"
            ),
            "summary": (
                iv.get("description") or ""
            ),
            "severity": NOTIFICATION_CRITICAL,
            "occurred_at": _iso(iv.get("created_at")),
            "ref_kind": "intervention",
            "ref_id": iv.get("id"),
            "ref_label": iv.get("title"),
        })

    # ---- Pending decisions ----------------------------------------
    for d in pending_decisions or []:
        if not isinstance(d, dict):
            continue
        notifications.append({
            "category": "pending_decision",
            "title": (
                f"Decision needs review: "
                f"{d.get('title') or 'Untitled'}"
            ),
            "summary": (
                f"Status: "
                f"{d.get('status') or 'PENDING'}"
            ),
            "severity": NOTIFICATION_WATCH,
            "occurred_at": _iso(d.get("created_at")),
            "ref_kind": "decision",
            "ref_id": d.get("id"),
            "ref_label": d.get("title"),
        })

    # ---- Premortem criticals --------------------------------------
    if recent_premortem_criticals and recent_premortem_criticals > 0:
        notifications.append({
            "category": "premortem_critical",
            "title": "Premortem surfaced critical failure modes",
            "summary": (
                f"{recent_premortem_criticals} CRITICAL mode(s) "
                f"identified in recent premortem runs"
            ),
            "severity": NOTIFICATION_CRITICAL,
            "occurred_at": _iso(now),
            "ref_kind": "premortem",
            "ref_id": None,
            "ref_label": None,
        })

    # Sort newest-first.
    notifications.sort(
        key=lambda n: (
            -int(
                _ensure_dt(n.get("occurred_at")).timestamp()
            ),
        ),
    )
    capped = notifications[:MAX_NOTIFICATIONS]
    notification_count = len(capped)

    # ---- Key signals --------------------------------------------
    critical_count = sum(
        1 for n in notifications
        if n.get("severity") == NOTIFICATION_CRITICAL
    )
    key_signals: list[dict] = []
    key_signals.append({
        "label": "notification_count",
        "value": notification_count,
        "severity": (
            "watch" if notification_count > 0 else "ok"
        ),
        "display": (
            f"{notification_count} notification(s) in inbox"
        ),
    })
    if critical_count:
        key_signals.append({
            "label": "critical_notification_count",
            "value": critical_count,
            "severity": "critical"
            if critical_count >= 2 else "watch",
            "display": (
                f"{critical_count} critical notification(s)"
            ),
        })

    # ---- Narrative ----------------------------------------------
    sentences: list[str] = []
    if notification_count == 0:
        sentences.append("Inbox is empty — nothing requires action.")
    else:
        sentences.append(
            f"{notification_count} item(s) in inbox; "
            f"{critical_count} are critical."
        )
    narrative = " ".join(sentences)

    return {
        "notification_count": notification_count,
        "notifications": capped,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_NOTIFICATIONS",
    "NOTIFICATION_CRITICAL",
    "NOTIFICATION_WATCH",
    "NOTIFICATION_INFO",
    "build_notifications",
]  # noqa: E501
