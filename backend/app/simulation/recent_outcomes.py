"""Pure helpers for the per-user recent-outcomes endpoint.

Composes a small "what happened recently?" payload:
the last 5 outcomes across the user's projects, suitable
for a dashboard widget.

The helper is pure-Python. The route layer passes a
list of recent outcome dicts (sorted by created_at
descending) and hands them to
:func:`build_recent_outcomes`.

Output shape
------------
::

    {
      "outcomes": list[dict],
      "outcome_count": int,
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


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_recent_outcomes(
    recent_outcome_dicts: list[dict] | None = None,
) -> dict:
    """Compose the per-user recent-outcomes digest.

    Args:
        recent_outcome_dicts: list of outcome dicts from
            the route layer. Each must expose
            ``outcome_id`` (or ``id``), ``project_id``,
            ``actual_conversion_rate`` (or
            ``actual_cr``), and ``created_at`` (or
            ``recorded_at``). The list is assumed to be
            already sorted by created_at descending.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    recent = []
    for entry in recent_outcome_dicts or []:
        if not isinstance(entry, dict):
            continue
        outcome_id = entry.get("outcome_id") or entry.get("id")
        project_id = entry.get("project_id")
        actual_cr = (
            entry.get("actual_conversion_rate")
            or entry.get("actual_cr")
        )
        created_at = entry.get("created_at") or entry.get(
            "recorded_at",
        )
        recent.append({
            "outcome_id": outcome_id,
            "project_id": project_id,
            "actual_conversion_rate": actual_cr,
            "created_at": _iso(created_at),
        })
    recent = recent[:MAX_RECENT]
    outcome_count = len(recent)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if outcome_count > 0:
        # Worst is the entry with the lowest actual_cr.
        worst = min(
            recent,
            key=lambda o: o["actual_conversion_rate"] or 0.0,
        )
        best = max(
            recent,
            key=lambda o: o["actual_conversion_rate"] or 0.0,
        )
        key_signals.append({
            "label": "recent_outcome_count",
            "value": outcome_count,
            "severity": (
                SIGNAL_OK
                if outcome_count >= 3
                else SIGNAL_WATCH
                if outcome_count >= 1
                else SIGNAL_CRITICAL
            ),
            "display": f"Recent outcomes: {outcome_count}",
        })

    # ---- Narrative ------------------------------------------------
    if outcome_count == 0:
        narrative = (
            "No recent outcomes yet - record a few to "
            "populate this tile."
        )
    else:
        worst_cr = worst["actual_conversion_rate"]
        best_cr = best["actual_conversion_rate"]
        if best is worst:
            narrative = (
                f"Last {outcome_count} outcome(s): best / "
                f"worst same at {best_cr}."
            )
        else:
            narrative = (
                f"Last {outcome_count} outcome(s): best "
                f"{best_cr} (project "
                f"{best['project_id']}), worst "
                f"{worst_cr} (project "
                f"{worst['project_id']})."
            )

    return {
        "outcomes": recent,
        "outcome_count": outcome_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_RECENT",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_recent_outcomes",
]  # noqa: E501