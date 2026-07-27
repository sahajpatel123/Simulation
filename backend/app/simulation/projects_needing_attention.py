"""Pure helpers for the per-user projects-needing-attention endpoint.

Composes a list of projects whose status-banner would
say "Action needed" or "Stale", so the dashboard can
surface a focused "what to look at next" widget.

The helper is pure-Python. The route layer builds
a list of per-project status rows and hands them to
:func:`build_projects_needing_attention`.

Output shape
------------
::

    {
      "needing_attention_count": int,
      "stale_count": int,
      "projects": list[{project_id, project_title, status, reason}],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Reasons for needing attention.
REASON_STALE_SIM: str = "stale_sim"
REASON_PENDING_DECISIONS: str = "pending_decisions"
REASON_LOW_OUTCOMES: str = "low_outcomes"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_projects_needing_attention(
    project_status_rows: list[dict] | None = None,
    stale_threshold_days: int = 14,
    low_outcome_ratio: float = 0.5,
) -> dict:
    """Compose the per-user projects-needing-attention digest.

    Args:
        project_status_rows: list of per-project dicts from
            the route layer. Each must expose ``project_id``,
            ``project_title``, ``status`` ('Stale' |
            'Action needed' | 'Healthy' | 'Empty' |
            'Unknown'), and optional ``sims_count``,
            ``outcomes_count``, ``pending_decisions``.
        stale_threshold_days: max days since latest sim
            for a project to NOT be flagged stale.
        low_outcome_ratio: min outcomes / sims ratio for a
            project to NOT be flagged "low outcomes".

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    projects: list[dict] = []
    stale_count = 0
    for row in project_status_rows or []:
        if not isinstance(row, dict):
            continue
        project_id = row.get("project_id")
        project_title = row.get("project_title")
        status = row.get("status")
        if status == "Stale":
            stale_count += 1
        needs_attention = status in ("Stale", "Action needed")
        if not needs_attention:
            continue
        reason = (
            REASON_PENDING_DECISIONS
            if status == "Action needed"
            else REASON_STALE_SIM
        )
        # Override reason for "Action needed" projects
        # where the route has flagged them for low outcomes.
        if (
            status == "Action needed"
            and _safe_int(row.get("sims_count")) > 0
            and _safe_int(row.get("outcomes_count"))
            < _safe_int(row.get("sims_count")) * low_outcome_ratio
        ):
            reason = REASON_LOW_OUTCOMES
        projects.append({
            "project_id": project_id,
            "project_title": project_title,
            "status": status,
            "reason": reason,
        })

    needing_attention_count = len(projects)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "needing_attention_count",
        "value": needing_attention_count,
        "severity": (
            SIGNAL_CRITICAL
            if needing_attention_count >= 3
            else SIGNAL_WATCH
            if needing_attention_count > 0
            else SIGNAL_OK
        ),
        "display": (
            f"{needing_attention_count} project(s) need attention"
        ),
    })

    # ---- Narrative ------------------------------------------------
    if needing_attention_count == 0:
        narrative = "All projects are in good shape - no action needed."
    else:
        narrative = (
            f"{needing_attention_count} project(s) need attention: "
            f"{stale_count} stale + "
            f"{needing_attention_count - stale_count} action-needed."
        )

    return {
        "needing_attention_count": needing_attention_count,
        "stale_count": stale_count,
        "projects": projects,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "REASON_STALE_SIM",
    "REASON_PENDING_DECISIONS",
    "REASON_LOW_OUTCOMES",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_projects_needing_attention",
]  # noqa: E501