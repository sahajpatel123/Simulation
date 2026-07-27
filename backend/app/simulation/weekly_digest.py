"""Pure helpers for the per-user weekly-digest endpoint.

Composes a single "what happened in my account this week?"
payload so the dashboard's weekly-email-preview tile can
render a founder-readable recap without fanning out to
multiple endpoints.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the rolling-7-day rows + projects list and
hands them to :func:`build_weekly_digest`.

What's inside
-------------
* ``sim_count_week``         - sims created in the last 7d
* ``decision_count_week``    - decisions enqueued in last 7d
* ``outcome_count_week``    - outcomes submitted in last 7d
* ``completed_sim_count_week`` - completed sims in last 7d
* ``calibration_trend_week`` - calibration health verdict
                                 for the rolling 7d window
                                 (output of build_calibration_health
                                 on the rows tagged COMPLETED
                                 within the window)
* ``quick_wins_total``      - quick wins across all projects
                               (union of intervention JSONs)
* ``top_failure_modes_total``- CRITICAL premortem modes
                               across all projects
* ``narrative``             - one paragraph
* ``key_signals``           - severity-tagged display dicts
"""
from __future__ import annotations

# Severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _classify_severity(count: int) -> str:
    """Severity for weekly-volume counts."""
    if count >= 5:
        return SIGNAL_OK
    if count >= 1:
        return SIGNAL_WATCH
    return SIGNAL_OK  # zero is fine


def build_weekly_digest(
    sim_count_week: int = 0,
    decision_count_week: int = 0,
    outcome_count_week: int = 0,
    completed_sim_count_week: int = 0,
    calibration_health: dict | None = None,
    quick_wins_total: int = 0,
    critical_failure_modes_total: int = 0,
) -> dict:
    """Compose the per-user weekly digest.

    Args:
        sim_count_week: total sims created in the last 7d.
        decision_count_week: total decisions enqueued
            in the last 7d.
        outcome_count_week: total outcomes submitted
            in the last 7d.
        completed_sim_count_week: subset of
            ``sim_count_week`` whose status is COMPLETED.
        calibration_health: pass-through output of
            ``build_calibration_health`` for the rolling
            7-day window (or ``None``).
        quick_wins_total: total low-difficulty + high-
            priority intervention items across the user's
            projects at snapshot time.
        critical_failure_modes_total: total CRITICAL
            premortem failure modes across projects at
            snapshot time.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    sim_count_week = _safe_int(sim_count_week)
    decision_count_week = _safe_int(decision_count_week)
    outcome_count_week = _safe_int(outcome_count_week)
    completed_sim_count_week = _safe_int(
        completed_sim_count_week,
    )
    quick_wins_total = _safe_int(quick_wins_total)
    critical_failure_modes_total = _safe_int(
        critical_failure_modes_total,
    )
    cal = calibration_health or {}

    # ---- Key signals -----------------------------------------------
    key_signals: list[dict] = []
    if sim_count_week:
        key_signals.append({
            "label": "sim_count_week",
            "value": sim_count_week,
            "severity": _classify_severity(sim_count_week),
            "display": (
                f"{sim_count_week} sim(s) in the last 7 days"
            ),
        })
    if decision_count_week:
        key_signals.append({
            "label": "decision_count_week",
            "value": decision_count_week,
            "severity": _classify_severity(
                decision_count_week,
            ),
            "display": (
                f"{decision_count_week} decision(s) enqueued "
                f"in the last 7 days"
            ),
        })
    if outcome_count_week:
        key_signals.append({
            "label": "outcome_count_week",
            "value": outcome_count_week,
            "severity": _classify_severity(
                outcome_count_week,
            ),
            "display": (
                f"{outcome_count_week} outcome(s) recorded "
                f"in the last 7 days"
            ),
        })
    if critical_failure_modes_total:
        key_signals.append({
            "label": "critical_failure_modes_total",
            "value": critical_failure_modes_total,
            "severity": (
                SIGNAL_CRITICAL
                if critical_failure_modes_total >= 3
                else SIGNAL_WATCH
            ),
            "display": (
                f"{critical_failure_modes_total} CRITICAL "
                f"failure mode(s) across projects"
            ),
        })
    if quick_wins_total:
        key_signals.append({
            "label": "quick_wins_total",
            "value": quick_wins_total,
            "severity": (
                SIGNAL_OK if quick_wins_total >= 2
                else SIGNAL_WATCH
            ),
            "display": (
                f"{quick_wins_total} quick win(s) ready "
                f"to act on"
            ),
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    total_activity = (
        sim_count_week
        + decision_count_week
        + outcome_count_week
    )
    if total_activity == 0:
        sentences.append(
            "Quiet week - no new sims, decisions, or "
            "outcomes in the last 7 days."
        )
    else:
        sentences.append(
            f"{total_activity} action(s) in the last 7 days: "
            f"{sim_count_week} sim(s), "
            f"{decision_count_week} decision(s), "
            f"{outcome_count_week} outcome(s)."
        )
    if critical_failure_modes_total and quick_wins_total:
        sentences.append(
            f"{critical_failure_modes_total} CRITICAL failure(s) "
            f"need attention; "
            f"{quick_wins_total} quick win(s) ready."
        )
    elif critical_failure_modes_total:
        sentences.append(
            f"{critical_failure_modes_total} CRITICAL failure(s) "
            f"need attention."
        )
    elif quick_wins_total:
        sentences.append(
            f"{quick_wins_total} quick win(s) ready to act on."
        )
    if outcome_count_week and sim_count_week:
        completion_rate = (
            completed_sim_count_week / sim_count_week
        ) if sim_count_week else 0.0
        if completion_rate >= 0.8:
            sentences.append(
                f"{int(completion_rate * 100)}% of this week's "
                f"sims reached COMPLETED status."
            )
    narrative = " ".join(sentences)

    return {
        "sim_count_week": sim_count_week,
        "decision_count_week": decision_count_week,
        "outcome_count_week": outcome_count_week,
        "completed_sim_count_week": completed_sim_count_week,
        "calibration_health": cal,
        "quick_wins_total": quick_wins_total,
        "critical_failure_modes_total": (
            critical_failure_modes_total
        ),
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_weekly_digest",
]  # noqa: E501