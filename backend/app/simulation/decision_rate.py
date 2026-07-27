"""Pure helpers for the per-user decision-rate endpoint.

Composes a single "how many decisions per sim?" payload:
the total number of decisions divided by the total
number of completed sims across the user's projects.
Useful for the dashboard's "decision utilization" widget.

The helper is pure-Python. The route layer builds the
(sim_count, decision_count) tuple and hands it to
:func:`build_decision_rate`.

Output shape
------------
::

    {
      "sim_count": int,
      "decision_count": int,
      "rate_per_sim": float | None,
      "verdict": "HIGH" | "NORMAL" | "LOW" | "INSUFFICIENT_DATA",
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Rate bands (decisions per sim).
HIGH_MIN: float = 1.0
NORMAL_MIN: float = 0.5

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


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


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


def build_decision_rate(
    sim_count: int = 0,
    decision_count: int = 0,
) -> dict:
    """Compose the per-user decision-rate digest.

    Args:
        sim_count: total completed sims across the
            user's projects.
        decision_count: total decisions across the
            user's projects.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    sim_count = _safe_int(sim_count)
    decision_count = _safe_int(decision_count)
    rate_per_sim: float | None = None
    if sim_count > 0:
        rate_per_sim = round(decision_count / sim_count, 2)

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
                f"{rate_per_sim} decision(s) per sim"
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
            f"Decision utilization is HIGH - "
            f"{rate_per_sim} decision(s) per sim "
            f"across {sim_count} sim(s)."
        )
    elif verdict == "NORMAL":
        narrative = (
            f"Decision utilization is NORMAL - "
            f"{rate_per_sim} decision(s) per sim. Consider "
            f"running decisions on more of your sims."
        )
    else:
        narrative = (
            f"Decision utilization is LOW - "
            f"{rate_per_sim} decision(s) per sim. Most of "
            f"your sims lack a corresponding decision."
        )

    return {
        "sim_count": sim_count,
        "decision_count": decision_count,
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
    "build_decision_rate",
]  # noqa: E501
