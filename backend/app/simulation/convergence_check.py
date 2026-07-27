"""Pure helpers for the simulation convergence check.

When a founder runs the same brief multiple times, do the
predicted conversion rates converge (good — stable) or
scatter (bad — unreliable)? Without this, the predicted
numbers aren't trustable.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the Simulation rows and hands them to
:func:`build_convergence_check`.

What "convergence" means here
-----------------------------
Given a list of ``predicted_conversion_rate`` values
across ``n`` sims with the same brief:

* ``mean_pcr`` — arithmetic mean of the predictions.
* ``std_dev`` — population standard deviation.
* ``cv`` — coefficient of variation = ``std_dev / mean``
  (normalises so a 0.5% spread at 1% prediction is
  comparable to a 0.5% spread at 10% prediction).
* ``verdict`` — one of:
  - ``CONVERGED``        : CV < 5%
  - ``MILDLY_VARIANT``   : 5% <= CV < 15%
  - ``DIVERGED``         : CV >= 15%

Output shape
------------
::

    {
      "sim_count": int,
      "mean_pcr": float,
      "std_dev": float,
      "cv": float,
      "verdict": "CONVERGED" | "MILDLY_VARIANT" | "DIVERGED",
      "min_pcr": float,
      "max_pcr": float,
      "range_pcr": float,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# CV thresholds — central product decision. Anything in
# 5-15% is "shows some variance but still usable"; 15%+
# is a red flag that predictions aren't reproducible.
CV_CONVERGED_THRESHOLD: float = 0.05
CV_DIVERGED_THRESHOLD: float = 0.15

# Minimum sim count for the verdict to be meaningful.
# Below this, even a low CV is misleading because the
# population is too small to be reliable.
MIN_SIMS_FOR_VERDICT: int = 3

# Cap on how many sims the route should consider.
MAX_SIMS_CONSIDERED: int = 25

VERDICT_CONVERGED: str = "CONVERGED"
VERDICT_MILDLY_VARIANT: str = "MILDLY_VARIANT"
VERDICT_DIVERGED: str = "DIVERGED"
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"

# Signal severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float_list(values: list[object]) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _classify_verdict(n: int, cv: float) -> str:
    if n < MIN_SIMS_FOR_VERDICT:
        return VERDICT_INSUFFICIENT_DATA
    if cv < CV_CONVERGED_THRESHOLD:
        return VERDICT_CONVERGED
    if cv < CV_DIVERGED_THRESHOLD:
        return VERDICT_MILDLY_VARIANT
    return VERDICT_DIVERGED


def _verdict_severity(verdict: str) -> str:
    if verdict == VERDICT_CONVERGED:
        return SIGNAL_OK
    if verdict == VERDICT_MILDLY_VARIANT:
        return SIGNAL_WATCH
    if verdict == VERDICT_DIVERGED:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH  # INSUFFICIENT_DATA → watch


def _format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_convergence_check(
    sims: list[dict],
) -> dict:
    """Compose the per-project convergence check.

    Args:
        sims: list of simulation-row dicts. Each must
            expose ``id``, ``created_at``, ``status``,
            ``predicted_conversion_rate`` (preferred) or
            ``results_json.mean_conversion_rate``.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    # ---- Collect predictions -----------------------------------------
    pcrs: list[float] = []
    sim_rows: list[dict] = []
    for s in sims:
        if not isinstance(s, dict):
            continue
        sim_rows.append(s)
        pcr = s.get("predicted_conversion_rate")
        if pcr is None:
            results = s.get("results_json") or {}
            if not isinstance(results, dict):
                results = {}
            pcr = results.get("mean_conversion_rate")
        if isinstance(pcr, (int, float)):
            pcrs.append(float(pcr))

    sim_count = len(sim_rows)
    usable = len(pcrs)

    # ---- Statistics --------------------------------------------------
    if usable == 0:
        return {
            "sim_count": sim_count,
            "mean_pcr": 0.0,
            "std_dev": 0.0,
            "cv": 0.0,
            "verdict": VERDICT_INSUFFICIENT_DATA,
            "min_pcr": 0.0,
            "max_pcr": 0.0,
            "range_pcr": 0.0,
            "narrative": (
                "No completed simulations with a recorded "
                "predicted conversion rate — the convergence "
                "check is empty."
            ),
            "key_signals": [],
        }

    mean_pcr = sum(pcrs) / usable
    if usable > 1:
        variance = sum((x - mean_pcr) ** 2 for x in pcrs) / usable
        std_dev = variance ** 0.5
    else:
        std_dev = 0.0

    cv = (std_dev / mean_pcr) if mean_pcr > 0 else 0.0
    verdict = _classify_verdict(usable, cv)
    severity = _verdict_severity(verdict)
    min_pcr = min(pcrs)
    max_pcr = max(pcrs)
    range_pcr = max_pcr - min_pcr

    # ---- Key signals -------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "sim_count",
        "value": sim_count,
        "severity": (
            SIGNAL_WATCH if sim_count < MIN_SIMS_FOR_VERDICT
            else SIGNAL_OK
        ),
        "display": f"{sim_count} sim(s) in the batch",
    })
    key_signals.append({
        "label": "cv",
        "value": round(cv, 6),
        "severity": severity,
        "display": (
            f"Coefficient of variation: {cv * 100:.1f}%"
        ),
    })
    key_signals.append({
        "label": "mean_predicted_conversion",
        "value": round(mean_pcr, 6),
        "severity": SIGNAL_OK,
        "display": (
            f"Mean predicted conversion: {_format_pct(mean_pcr)}"
        ),
    })

    # ---- Narrative ---------------------------------------------------
    sentences: list[str] = []
    if usable < MIN_SIMS_FOR_VERDICT:
        sentences.append(
            f"Only {usable} sim(s) have a recorded predicted "
            f"conversion rate — run at least "
            f"{MIN_SIMS_FOR_VERDICT} to make a verdict."
        )
    elif verdict == VERDICT_CONVERGED:
        sentences.append(
            f"Predictions are stable across {usable} sim(s): "
            f"mean {_format_pct(mean_pcr)}, CV {cv * 100:.1f}%."
        )
    elif verdict == VERDICT_MILDLY_VARIANT:
        sentences.append(
            f"Predictions show some variance across {usable} "
            f"sim(s): mean {_format_pct(mean_pcr)}, CV "
            f"{cv * 100:.1f}%."
        )
    else:
        sentences.append(
            f"Predictions diverge across {usable} sim(s): "
            f"mean {_format_pct(mean_pcr)}, CV {cv * 100:.1f}% "
            f"(>= {CV_DIVERGED_THRESHOLD * 100:.0f}%). "
            f"Range {_format_pct(range_pcr)}."
        )
    if usable >= 2 and verdict == VERDICT_DIVERGED:
        sentences.append(
            "Check whether assumptions or environment changed "
            "between runs."
        )
    narrative = " ".join(sentences)

    return {
        "sim_count": sim_count,
        "mean_pcr": round(mean_pcr, 6),
        "std_dev": round(std_dev, 6),
        "cv": round(cv, 6),
        "verdict": verdict,
        "min_pcr": round(min_pcr, 6),
        "max_pcr": round(max_pcr, 6),
        "range_pcr": round(range_pcr, 6),
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "CV_CONVERGED_THRESHOLD",
    "CV_DIVERGED_THRESHOLD",
    "MIN_SIMS_FOR_VERDICT",
    "MAX_SIMS_CONSIDERED",
    "VERDICT_CONVERGED",
    "VERDICT_MILDLY_VARIANT",
    "VERDICT_DIVERGED",
    "VERDICT_INSUFFICIENT_DATA",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_convergence_check",
]  # noqa: E501
