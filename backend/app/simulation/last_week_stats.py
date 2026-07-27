"""Pure helpers for the per-user last-week-stats endpoint.

Composes comparative stats: this week (last 7 days) vs
last week (days 8-14 ago) for the user. Shows whether
activity is accelerating, steady, or slowing.

The helper is pure-Python. The route layer builds the
(this_week_counts, last_week_counts) pair and hands it
to :func:`build_last_week_stats`.

Output shape
------------
::

    {
      "this_week": {"sim_count": int, "decision_count": int, "outcome_count": int},
      "last_week": {"sim_count": int, "decision_count": int, "outcome_count": int},
      "deltas": {"sim_count": int, "decision_count": int, "outcome_count": int},
      "verdict": "ACCELERATING" | "STEADY" | "SLOWING" | "INSUFFICIENT_DATA",
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Verdict threshold: 50% change required to call it
# accelerating/slowing.
ACCELERATION_THRESHOLD: float = 0.5

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _verdict_severity(verdict: str) -> str:
    if verdict == "ACCELERATING":
        return SIGNAL_OK
    if verdict == "SLOWING":
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH  # STEADY or INSUFFICIENT_DATA


def _compute_delta(this_week: int, last_week: int) -> int:
    return this_week - last_week


def _is_accelerating(this_week: int, last_week: int) -> bool:
    if last_week == 0:
        return this_week > 0
    return (
        this_week - last_week
    ) / last_week >= ACCELERATION_THRESHOLD


def _is_slowing(this_week: int, last_week: int) -> bool:
    if last_week == 0:
        return False
    return (
        last_week - this_week
    ) / last_week >= ACCELERATION_THRESHOLD


def build_last_week_stats(
    this_week_counts: dict | None = None,
    last_week_counts: dict | None = None,
) -> dict:
    """Compose the per-user last-week-stats digest.

    Args:
        this_week_counts: dict with keys sim_count,
            decision_count, outcome_count for the last
            7 days.
        last_week_counts: dict with the same keys for
            days 8-14 ago.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    this_week = {
        "sim_count": _safe_int(
            (this_week_counts or {}).get("sim_count"),
        ),
        "decision_count": _safe_int(
            (this_week_counts or {}).get("decision_count"),
        ),
        "outcome_count": _safe_int(
            (this_week_counts or {}).get("outcome_count"),
        ),
    }
    last_week = {
        "sim_count": _safe_int(
            (last_week_counts or {}).get("sim_count"),
        ),
        "decision_count": _safe_int(
            (last_week_counts or {}).get("decision_count"),
        ),
        "outcome_count": _safe_int(
            (last_week_counts or {}).get("outcome_count"),
        ),
    }

    deltas = {
        key: _compute_delta(this_week[key], last_week[key])
        for key in this_week
    }

    this_total = sum(this_week.values())
    last_total = sum(last_week.values())

    if this_total == 0 and last_total == 0:
        verdict = "INSUFFICIENT_DATA"
    elif _is_accelerating(this_total, last_total):
        verdict = "ACCELERATING"
    elif _is_slowing(this_total, last_total):
        verdict = "SLOWING"
    else:
        verdict = "STEADY"
    severity = _verdict_severity(verdict)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "verdict",
        "value": verdict,
        "severity": severity,
        "display": f"Activity trend: {verdict.lower()}",
    })

    # ---- Narrative ------------------------------------------------
    if verdict == "INSUFFICIENT_DATA":
        narrative = (
            "Not enough activity to compare weeks - run a "
            "few sims/decisions/outcomes to populate this tile."
        )
    else:
        direction = (
            "up" if verdict == "ACCELERATING" else
            "down" if verdict == "SLOWING" else
            "steady"
        )
        narrative = (
            f"Activity is {direction} - "
            f"this week {this_total} action(s) vs "
            f"last week {last_total} action(s). "
            f"Sims {deltas['sim_count']:+d}, "
            f"decisions {deltas['decision_count']:+d}, "
            f"outcomes {deltas['outcome_count']:+d}."
        )

    return {
        "this_week": this_week,
        "last_week": last_week,
        "deltas": deltas,
        "verdict": verdict,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "ACCELERATION_THRESHOLD",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_last_week_stats",
]  # noqa: E501
