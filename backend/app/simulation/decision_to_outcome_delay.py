"""Pure helpers for the per-user decision-to-outcome-delay endpoint.

Composes a single "how long after a decision do you
record an outcome?" payload: the average gap between a
decision and the next outcome on the same project.
Complements decision-velocity (sim→decision) and
outcome-velocity (sim→outcome) with the missing
decision→outcome chain.

The helper is pure-Python. The route layer builds
the (decision_at, next_outcome_at) pairs and hands them
to :func:`build_decision_to_outcome_delay`.

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
FAST_MAX_HOURS: float = 24.0
NORMAL_MAX_HOURS: float = 168.0  # 7 days

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
    return SIGNAL_WATCH


def build_decision_to_outcome_delay(
    decision_outcome_pairs: list[tuple] | None = None,
) -> dict:
    """Compose the per-user decision-to-outcome-delay digest.

    Args:
        decision_outcome_pairs: list of
            ``(decision_at, next_outcome_at)`` tuples
            (datetimes or ISO strings). When either element
            is missing/invalid, that pair is skipped.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    gaps_hours: list[float] = []
    for pair in decision_outcome_pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        dec_dt = pair[0]
        out_dt = pair[1]
        if dec_dt is None or out_dt is None:
            continue
        if isinstance(dec_dt, str):
            from datetime import datetime
            try:
                dec_dt = datetime.fromisoformat(dec_dt)
            except Exception:
                continue
        if isinstance(out_dt, str):
            from datetime import datetime
            try:
                out_dt = datetime.fromisoformat(out_dt)
            except Exception:
                continue
        if not hasattr(dec_dt, "timestamp"):
            continue
        if not hasattr(out_dt, "timestamp"):
            continue
        delta = out_dt - dec_dt
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
                f"Average decision->outcome gap: "
                f"{average_gap_hours}h"
            ),
        })

    # ---- Narrative ------------------------------------------------
    if sample_count == 0:
        narrative = (
            "Not enough decision+outcome data yet - run a "
            "few decisions + outcomes to populate this tile."
        )
    elif verdict == "FAST":
        narrative = (
            f"Decision->outcome loop is FAST - average "
            f"gap is {average_gap_hours}h across "
            f"{sample_count} decision(s)."
        )
    elif verdict == "NORMAL":
        narrative = (
            f"Decision->outcome loop is NORMAL - average "
            f"gap is {average_gap_hours}h."
        )
    else:
        narrative = (
            f"Decision->outcome loop is SLOW - average "
            f"gap is {average_gap_hours}h. Consider "
            f"recording outcomes faster after decisions."
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
    "build_decision_to_outcome_delay",
]  # noqa: E501
