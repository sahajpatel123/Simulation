"""Pure helpers for the per-project status-banner endpoint.

Composes a single one-liner status string ("Healthy" /
"Stale" / "Action needed") for the project header. Cheap
to fetch, useful for surfacing the project's state at a
glance.

The helper is pure-Python. The route layer pulls the
counts and hands them to :func:`build_status_banner`.

Status logic
-----------
* "Healthy"   - the project has a recent COMPLETED sim
                AND no pending decisions
* "Stale"      - no recent activity (no sim in 14d, no
                decisions in 14d)
* "Action needed" - has pending decisions, OR the sim is
                older than 7d, OR the assumption
                extraction is older than 30d
* "Empty"      - no brief, no assumptions, no sims
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Threshold (days) for the latest sim to count as
# "recent" - below this, the project is considered
# "current".
SIM_RECENT_DAYS: int = 7
# Above this, the project is considered "stale" (no
# meaningful activity).
SIM_STALE_DAYS: int = 14
# Above this, the assumption extraction is considered
# stale.
ASSUMPTION_STALE_DAYS: int = 30


def build_status_banner(
    brief_completed: bool,
    assumption_count: int,
    has_completed_sim: bool,
    days_since_latest_sim: int | None,
    pending_decision_count: int,
    days_since_latest_assumption_extraction: int | None,
) -> dict:
    """Compose the per-project status banner.

    Args:
        brief_completed: ``True`` when project.brief_completed_at is set.
        assumption_count: count of non-hidden assumptions.
        has_completed_sim: ``True`` when the project has
            at least one COMPLETED sim.
        days_since_latest_sim: ``None`` when no sim, else
            the days-since-latest-completed-sim.
        pending_decision_count: count of PENDING/RUNNING
            decisions.
        days_since_latest_assumption_extraction: ``None``
            when no assumption row, else the days-since-
            latest-assumption.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    has_brief = brief_completed
    has_assumptions = assumption_count > 0

    if not has_brief and not has_assumptions and not has_completed_sim:
        status = "Empty"
        severity = SIGNAL_WATCH
    elif (
        has_completed_sim
        and pending_decision_count == 0
        and (days_since_latest_sim is None or
             days_since_latest_sim <= SIM_RECENT_DAYS)
    ):
        status = "Healthy"
        severity = SIGNAL_OK
    elif (
        days_since_latest_sim is None
        or days_since_latest_sim > SIM_STALE_DAYS
    ):
        status = "Stale"
        severity = SIGNAL_CRITICAL
    else:
        # Has recent activity AND pending decisions OR
        # old assumption extraction = action needed.
        if (
            pending_decision_count > 0
            or (
                days_since_latest_assumption_extraction is not None
                and days_since_latest_assumption_extraction
                > ASSUMPTION_STALE_DAYS
            )
        ):
            status = "Action needed"
            severity = SIGNAL_WATCH
        else:
            status = "Healthy"
            severity = SIGNAL_OK

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "status",
        "value": status,
        "severity": severity,
        "display": f"Project status: {status}",
    })

    # ---- Narrative ------------------------------------------------
    if status == "Empty":
        narrative = (
            "Project is empty - finish the brief, then run "
            "extract-assumptions to start."
        )
    elif status == "Healthy":
        narrative = (
            "Project is up to date. Latest simulation is "
            "recent, no pending decisions."
        )
    elif status == "Stale":
        if days_since_latest_sim is None:
            narrative = (
                "No simulation has been run yet. Start one "
                "to see predictions."
            )
        else:
            narrative = (
                f"No new simulation in {days_since_latest_sim} "
                f"day(s). Consider re-running."
            )
    else:
        # Action needed
        bits: list[str] = []
        if pending_decision_count > 0:
            bits.append(
                f"{pending_decision_count} decision(s) pending"
            )
        if (
            days_since_latest_assumption_extraction is not None
            and days_since_latest_assumption_extraction
            > ASSUMPTION_STALE_DAYS
        ):
            bits.append(
                f"assumption extraction is "
                f"{days_since_latest_assumption_extraction}d old"
            )
        narrative = (
            "Action needed: " + ", ".join(bits) + "."
        )

    return {
        "status": status,
        "severity": severity,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIM_RECENT_DAYS",
    "SIM_STALE_DAYS",
    "ASSUMPTION_STALE_DAYS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_status_banner",
]  # noqa: E501