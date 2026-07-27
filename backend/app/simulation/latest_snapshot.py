"""Pure helpers for the per-project latest-snapshot endpoint.

Composes a focused "what is the current state of this
project?" payload. Different from project-export
(historical full bundle) and from projects-summary
(per-user grid). This is per-project, fast, latest-only.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls each source's "latest" entry and hands them
to :func:`build_latest_snapshot`.

Output shape
------------
::

    {
      "project_id": int,
      "project_title": str,
      "project_status": str,
      "brief_completed": bool,
      "latest_simulation": {...} | None,
      "latest_decision": {...} | None,
      "latest_outcome": {...} | None,
      "latest_assumption_extraction": {...} | None,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import datetime, timezone

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


def _compact(row: dict | None, keys: list[str]) -> dict | None:
    """Project a DB-row dict down to a compact summary
    card containing only the listed keys.
    """
    if not isinstance(row, dict):
        return None
    out: dict = {}
    for key in keys:
        if key in row:
            value = row[key]
            if hasattr(value, "isoformat"):
                try:
                    value = value.isoformat()
                except Exception:
                    pass
            out[key] = value
    return out or None


def build_latest_snapshot(
    project_id: int | None,
    project_title: str | None,
    project_status: str | None,
    brief_completed: bool,
    latest_simulation_row: dict | None,
    latest_decision_row: dict | None,
    latest_outcome_row: dict | None,
    latest_assumption_row: dict | None,
) -> dict:
    """Compose the per-project latest-snapshot digest.

    Args:
        project_id: project id (for echo into the response).
        project_title: project title for the narrative.
        project_status: latest project status (from the
            Project row).
        brief_completed: ``True`` when the brief is
            marked completed.
        latest_*_row: latest DB-row dict (or ``None``) for
            simulations, decisions, outcomes, assumptions
            respectively. The helper pulls only the
            dashboard-friendly fields.
    """
    latest_simulation = _compact(latest_simulation_row, [
        "id", "status", "created_at", "updated_at",
        "predicted_conversion_rate", "actual_conversion_rate",
        "confidence_score",
    ])
    latest_decision = _compact(latest_decision_row, [
        "id", "title", "status", "created_at",
    ])
    latest_outcome = _compact(latest_outcome_row, [
        "id", "created_at", "actual_conversion_rate",
        "actual_mrr", "calibration_score",
    ])
    latest_assumption_extraction = None
    if isinstance(latest_assumption_row, dict):
        text = latest_assumption_row.get("text")
        if text is not None or latest_assumption_row.get(
            "created_at"
        ) is not None:
            latest_assumption_extraction = _compact(
                latest_assumption_row,
                ["id", "text", "sensitivity", "created_at"],
            )

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"Project {project_id or '?'} ({project_title or '?'}): "
        f"status {project_status or 'UNKNOWN'}."
    )
    if brief_completed:
        sentences.append("Brief completed.")
    else:
        sentences.append("Brief incomplete.")
    if latest_simulation:
        sentences.append(
            "Has a completed simulation."
        )
    if latest_outcome:
        sentences.append(
            "Has a recorded outcome."
        )
    if latest_decision:
        sentences.append(
            "Has a pending or completed decision."
        )
    narrative = " ".join(sentences)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "latest_simulation_present",
        "value": latest_simulation is not None,
        "severity": (
            SIGNAL_OK
            if latest_simulation is not None
            else SIGNAL_WATCH
        ),
        "display": (
            "Latest simulation present"
            if latest_simulation is not None
            else "No simulation yet"
        ),
    })
    key_signals.append({
        "label": "latest_outcome_present",
        "value": latest_outcome is not None,
        "severity": (
            SIGNAL_OK
            if latest_outcome is not None
            else SIGNAL_WATCH
        ),
        "display": (
            "Latest outcome present"
            if latest_outcome is not None
            else "No outcome yet"
        ),
    })
    key_signals.append({
        "label": "brief_completed",
        "value": brief_completed,
        "severity": (
            SIGNAL_OK if brief_completed else SIGNAL_WATCH
        ),
        "display": (
            "Brief completed"
            if brief_completed
            else "Brief incomplete"
        ),
    })

    return {
        "project_id": project_id,
        "project_title": project_title,
        "project_status": project_status or "UNKNOWN",
        "brief_completed": brief_completed,
        "latest_simulation": latest_simulation,
        "latest_decision": latest_decision,
        "latest_outcome": latest_outcome,
        "latest_assumption_extraction": (
            latest_assumption_extraction
        ),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_latest_snapshot",
]  # noqa: E501
