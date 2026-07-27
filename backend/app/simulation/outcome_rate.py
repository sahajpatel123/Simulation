"""Pure helpers for the per-user outcome-rate endpoint.

Composes a single "how many outcomes per sim?" payload:
the total number of outcomes divided by the total number
of completed sims across the user's projects. Analog of
/me/decision-rate but for outcomes.

The helper is pure-Python. The route layer builds the
(sim_count, outcome_count) tuple and hands it to
:func:`build_outcome_rate`.

Output shape
------------
::

    {
      "sim_count": int,
      "outcome_count": int,
      "rate_per_sim": float | None,
      "verdict": "HIGH" | "NORMAL" | "LOW" | "INSUFFICIENT_DATA",
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Rate bands (outcomes per sim).
HIGH_MIN: float = 0.5
NORMAL_MIN: float = 0.25

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


def _classify_verdict(rate: float | None) -> str:
    if rate is None:
        return "INSUFFICIENT_DATA"
    if rate >= HIGH_MIN:
        return "HIGH"
    if rate >= NORMAL_MIN:
        return "NORMAL"
    return "LOW"


def _verdict_severity(verdict: str) -> str:
    if verdict == "HIGH":
        return SIGNAL_OK
    if verdict == "LOW":
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def build_outcome_rate(
    sim_count: int = 0,
    outcome_count: int = 0,
) -> dict:
    """Compose the per-user outcome-rate digest.

    Args:
        sim_count: total completed sims across the
            user's projects.
        outcome_count: total outcomes across the user's
            projects.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    sim_count = _safe_int(sim_count)
    outcome_count = _safe_int(outcome_count)
    rate_per_sim: float | None = None
    if sim_count > 0:
        rate_per_sim = round(outcome_count / sim_count, 2)

    verdict = _classify_verdict(rate_per_sim)
    severity = _verdict_severity(verdict)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if rate_per_sim is not None:
        key_signals.append({
            "label": "rate_per_sim",
            "value": rate_per_sim,
            "severity": severity,
            "display": (
                f"{rate_per_sim} outcome(s) per sim"
            ),
        })

    # ---- Narrative ------------------------------------------------
    if sim_count == 0:
        narrative = (
            "No completed simulations yet - run a few sims "
            "to populate this tile."
        )
    elif verdict == "HIGH":
        narrative = (
            f"Outcome coverage is HIGH - "
            f"{rate_per_sim} outcome(s) per sim "
            f"across {sim_count} sim(s)."
        )
    elif verdict == "NORMAL":
        narrative = (
            f"Outcome coverage is NORMAL - "
            f"{rate_per_sim} outcome(s) per sim. Consider "
            f"recording outcomes on more of your sims."
        )
    else:
        narrative = (
            f"Outcome coverage is LOW - "
            f"{rate_per_sim} outcome(s) per sim. Most of "
            f"your sims lack a corresponding outcome."
        )

    return {
        "sim_count": sim_count,
        "outcome_count": outcome_count,
        "rate_per_sim": rate_per_sim,
        "verdict": verdict,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "HIGH_MIN",
    "NORMAL_MIN",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_outcome_rate",
]  # noqa: E501
