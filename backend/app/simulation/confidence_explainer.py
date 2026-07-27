"""Pure helpers for the per-project confidence-explainer endpoint.

Decomposes the latest completed sim's confidence score
into its contributing factors so the dashboard can show
'why is my confidence 0.85?' instead of just '0.85'.

The helper is pure-Python. The route layer pulls the
latest sim + the supporting facts and hands them to
:func:`build_confidence_explainer`.

What's in the decomposition
---------------------------
* ``sample_volume`` - sim's consumer_volume (proxy
  for the agent population that ran)
* ``agreement_rate`` - % of agents who converted
  (proxy: predicted_conversion_rate + cluster variance)
* ``assumption_coverage`` - 0..1 fraction = "do we have
  assumptions covering every sensitivity band?"
* ``days_since_latest_assumption`` - older assumptions
  reduce confidence
* ``outcome_history_depth`` - number of past outcomes
  used to calibrate (more = better)
* ``confidence_score`` - the existing sim.confidence_score
  (0-1)

Output shape
------------
::

    {
      "confidence_score": float,
      "factors": list[{label, value, weight_pct, contribution}],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

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


def build_confidence_explainer(
    confidence_score: float | None = None,
    sample_volume: int = 0,
    consumer_volume_total: int = 0,
    agreement_rate: float | None = None,
    assumption_coverage: float = 0.0,
    days_since_latest_assumption: int | None = None,
    outcome_history_depth: int = 0,
) -> dict:
    """Compose the per-project confidence-explainer digest.

    Args:
        confidence_score: 0..1 from the latest sim
            (``sim.confidence_score`` or
            ``results_json.aggregated.confidence_score``).
        sample_volume: count of agents the sim ran
            (``sim.consumer_volume``).
        consumer_volume_total: env-defined
            ``consumer_volume`` (the simulated total).
        agreement_rate: 0..1 fraction of agents that
            converted (predicted_conversion_rate * 1.0).
        assumption_coverage: 0..1 fraction (HIGH/CRITICAL
            coverage / total sensitivity slots).
        days_since_latest_assumption: age in days of the
            most recent assumption row (or None when no
            assumption).
        outcome_history_depth: count of past outcomes
            used to calibrate the sim.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    confidence = _safe_float(confidence_score) or 0.0

    # ---- Factor values --------------------------------------------
    # 1) Sample volume factor (0..1). A 10k-agent sim is
    # a strong signal; <1k is weak.
    sample_factor = 0.0
    if sample_volume > 0:
        if sample_volume >= 5000:
            sample_factor = 1.0
        elif sample_volume >= 1000:
            sample_factor = 0.7
        elif sample_volume >= 500:
            sample_factor = 0.4
        else:
            sample_factor = 0.2

    # 2) Agreement factor (0..1). Use the predicted
    # conversion rate as a proxy - low predictions imply
    # sparse evidence at the conversion boundary.
    agreement_value = _safe_float(agreement_rate)
    if agreement_value is not None:
        # A prediction between 1% and 10% is in the
        # "trustable" band. Outside, confidence drops.
        if 0.01 <= agreement_value <= 0.10:
            agreement_factor = 1.0
        elif 0.005 <= agreement_value <= 0.20:
            agreement_factor = 0.7
        else:
            agreement_factor = 0.3
    else:
        agreement_factor = 0.5  # unknown

    # 3) Assumption coverage factor.
    coverage_factor = max(0.0, min(1.0, assumption_coverage))

    # 4) Assumption freshness factor.
    if days_since_latest_assumption is None:
        freshness_factor = 0.0
    elif days_since_latest_assumption <= 7:
        freshness_factor = 1.0
    elif days_since_latest_assumption <= 30:
        freshness_factor = 0.7
    elif days_since_latest_assumption <= 60:
        freshness_factor = 0.4
    else:
        freshness_factor = 0.2

    # 5) Outcome history factor.
    if outcome_history_depth >= 3:
        history_factor = 1.0
    elif outcome_history_depth >= 1:
        history_factor = 0.7
    else:
        history_factor = 0.3

    factors = [
        {
            "label": "Sample volume",
            "value": sample_volume,
            "factor": sample_factor,
        },
        {
            "label": "Conversion agreement",
            "value": agreement_rate,
            "factor": agreement_factor,
        },
        {
            "label": "Assumption coverage",
            "value": round(coverage_factor, 3),
            "factor": coverage_factor,
        },
        {
            "label": "Assumption freshness",
            "value": days_since_latest_assumption,
            "factor": freshness_factor,
        },
        {
            "label": "Outcome history depth",
            "value": outcome_history_depth,
            "factor": history_factor,
        },
    ]

    # ---- Key signals ----------------------------------------------
    severity = (
        SIGNAL_OK
        if confidence >= 0.7
        else SIGNAL_WATCH
        if confidence >= 0.4
        else SIGNAL_CRITICAL
    )
    key_signals: list[dict] = []
    key_signals.append({
        "label": "confidence_score",
        "value": round(confidence, 4),
        "severity": severity,
        "display": f"Confidence: {confidence * 100:.0f}%",
    })

    # ---- Narrative ------------------------------------------------
    if confidence >= 0.7:
        head = "Confidence is high."
    elif confidence >= 0.4:
        head = "Confidence is moderate."
    else:
        head = "Confidence is low."

    # Highlight weakest factor.
    weakest = min(factors, key=lambda f: f["factor"])
    if weakest["factor"] < 0.5:
        narrative = (
            f"{head} Weakest factor: {weakest['label']} "
            f"({weakest['factor']:.2f})."
        )
    else:
        narrative = head

    return {
        "confidence_score": round(confidence, 4),
        "factors": factors,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_confidence_explainer",
]  # noqa: E501