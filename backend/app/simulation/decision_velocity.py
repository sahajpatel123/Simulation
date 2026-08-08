"""Pure helpers for the per-user decision-velocity endpoint.

Composes a single "how fast do you decide?" payload:
the average gap between a completed sim and the user's
first decision on that project. Useful for the
dashboard's "decision speed" widget.

The helper is pure-Python. The route layer builds the
list of (sim_completed_at, first_decision_at) pairs and
hands them to :func:`build_decision_velocity`.

Output shape
------------
::

    {
      "sample_count": int,
      "average_gap_hours": float | None,
      "median_gap_hours": float | None,
      "fastest_gap_hours": float | None,
      "slowest_gap_hours": float | None,
      "verdict": "FAST" | "NORMAL" | "SLOW" | "INSUFFICIENT_DATA",
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Verdict bands (hours).
FAST_MAX_HOURS: float = 4.0
NORMAL_MAX_HOURS: float = 24.0

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def _classify_verdict(average_hours: float | None) -> str:
    if average_hours is None:
        return "INSUFFICIENT_DATA"
    if average_hours <= FAST_MAX_HOURS:
        return "FAST"
    if average_hours <= NORMAL_MAX_HOURS:
        return "NORMAL"
    return "SLOW"


def _verdict_severity(verdict: str) -> str:
    if verdict == "FAST":
        return SIGNAL_OK
    if verdict == "SLOW":
        return SIGNAL_CRITICAL
    if verdict == "NORMAL":
        return SIGNAL_WATCH
    return SIGNAL_WATCH  # INSUFFICIENT_DATA


def build_decision_velocity(
    sim_decision_pairs: list[tuple] | None = None,
) -> dict:
    """Compose the per-user decision-velocity digest.

    Args:
        sim_decision_pairs: list of
            ``(sim_completed_at, first_decision_at)`` tuples
            (datetimes or ISO strings). When either element
            is missing/invalid, that pair is skipped.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    gaps_hours: list[float] = []
    for pair in sim_decision_pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        sim_dt = pair[0]
        dec_dt = pair[1]
        if sim_dt is None or dec_dt is None:
            continue
        # Allow ISO strings.
        if isinstance(sim_dt, str):
            from datetime import datetime
            try:
                sim_dt = datetime.fromisoformat(sim_dt)
            except Exception:
                continue
        if isinstance(dec_dt, str):
            from datetime import datetime
            try:
                dec_dt = datetime.fromisoformat(dec_dt)
            except Exception:
                continue
        if not hasattr(sim_dt, "timestamp"):
            continue
        if not hasattr(dec_dt, "timestamp"):
            continue
        delta = dec_dt - sim_dt
        # Decision must be AFTER sim completion (negative
        # gaps are nonsense - skip).
        seconds = delta.total_seconds()
        if seconds < 0:
            continue
        gaps_hours.append(seconds / 3600.0)

    sample_count = len(gaps_hours)
    average_gap_hours: float | None = None
    median_gap_hours: float | None = None
    fastest_gap_hours: float | None = None
    slowest_gap_hours: float | None = None
    if sample_count > 0:
        average_gap_hours = round(
            sum(gaps_hours) / sample_count, 2,
        )
        sorted_gaps = sorted(gaps_hours)
        mid = sample_count // 2
        if sample_count % 2 == 0:
            median_gap_hours = round(
                (sorted_gaps[mid - 1] + sorted_gaps[mid]) / 2,
                2,
            )
        else:
            median_gap_hours = round(sorted_gaps[mid], 2)
        fastest_gap_hours = round(sorted_gaps[0], 2)
        slowest_gap_hours = round(sorted_gaps[-1], 2)

    verdict = _classify_verdict(average_gap_hours)
    severity = _verdict_severity(verdict)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if sample_count > 0:
        key_signals.append({
            "label": "average_gap_hours",
            "value": average_gap_hours,
            "severity": severity,
            "display": (
                f"Average decision gap: "
                f"{average_gap_hours}h"
            ),
        })

    # ---- Narrative ------------------------------------------------
    if sample_count == 0:
        narrative = (
            "Not enough decision data yet - run a few sims "
            "+ decisions to populate this tile."
        )
    elif verdict == "FAST":
        narrative = (
            f"Decision velocity is FAST - average gap is "
            f"{average_gap_hours}h across {sample_count} sim(s)."
        )
    elif verdict == "NORMAL":
        narrative = (
            f"Decision velocity is NORMAL - average gap is "
            f"{average_gap_hours}h."
        )
    else:
        narrative = (
            f"Decision velocity is SLOW - average gap is "
            f"{average_gap_hours}h. Consider resolving "
            f"decisions faster."
        )

    return {
        "sample_count": sample_count,
        "average_gap_hours": average_gap_hours,
        "median_gap_hours": median_gap_hours,
        "fastest_gap_hours": fastest_gap_hours,
        "slowest_gap_hours": slowest_gap_hours,
        "verdict": verdict,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "FAST_MAX_HOURS",
    "NORMAL_MAX_HOURS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_decision_velocity",
]  # noqa: E501
