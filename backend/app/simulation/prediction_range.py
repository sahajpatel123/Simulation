"""
Accuracy-adjusted prediction-range digest for a completed simulation.

The conductor produces a single predicted conversion rate, but a founder
needs to know *how much to trust that number*. This module blends the run's
predicted conversion with the historical (predicted, actual) outcome pairs to
emit a realistic range: ``[low, high]`` around the prediction.

Logic:

* Reuse :func:`app.simulation.outcomes_digest.aggregate_outcomes` for MAE /
  RMSE and the standard confidence label.
* The range width is ``max(MAE, RMSE x 0.8)`` widened by 1.5x on small
  samples (<10 outcomes) and capped at 30pp so a poor historical record can't
  produce a meaningless near-0..100% band.
* Pairs with a missing, non-numeric, boolean, or non-finite conversion rate
  on either side are dropped before aggregation; out-of-range values are
  clamped to ``[0, 1]`` so one bad data row can't poison the calibration.
* With no recorded outcomes the helper still returns a conservative default
  band (predicted ± 5pp) so the dashboard always has a range to render, but
  labels it ``INSUFFICIENT_DATA``.

Pure module — no DB, no I/O. The route layer supplies the predicted rate and
the historical pairs.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.simulation.outcomes_digest import (
    LABEL_INSUFFICIENT_DATA,
    LABEL_NEEDS_ATTENTION,
    LABEL_POORLY_CALIBRATED,
    LABEL_WELL_CALIBRATED,
    NEEDS_ATTENTION_MAX_MAE,
    WELL_CALIBRATED_MAX_MAE,
    aggregate_outcomes,
)

# Minimum number of (predicted, actual) pairs before historical calibration
# is considered real signal. Below this the payload is explicitly labelled
# INSUFFICIENT_DATA even though a conservative range is still rendered.
MIN_OUTCOMES_FOR_RANGE: int = 3

# Below this many pairs the range is widened because small samples have more
# sampling noise than the point MAE/RMSE implies.
SMALL_SAMPLE_COUNT: int = 10
SMALL_SAMPLE_WIDENING: float = 1.5

# RMSE is weighted into the spread alongside MAE so outlier-rich histories
# widen the band a little without letting one bad outcome dominate.
RMSE_WEIGHT: float = 0.8

# Hard bounds for the spread.
MIN_SPREAD: float = 0.02
MAX_SPREAD: float = 0.30

# When there are no recorded outcomes at all, use a conservative default band
# so the UI always has something to render.
DEFAULT_SPREAD: float = 0.05


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _rate(value: Any) -> float | None:
    """Parse a conversion rate to ``[0, 1]`` or ``None`` when unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def _usable_pair(
    predicted: Any,
    actual: Any,
) -> tuple[float, float] | None:
    """Normalize one historical pair, or return ``None`` when unusable.

    Only pairs with a finite, numeric conversion rate on *both* sides can
    teach the calibration layer. Anything else (``None``, a non-numeric
    string, a boolean, ``NaN``, or an out-of-range value) is dropped before
    aggregation so the sample count and error metrics always describe the
    same usable set.
    """
    pred = _rate(predicted)
    act = _rate(actual)
    if pred is None or act is None:
        return None
    return pred, act


def extract_predicted_conversion(results: Any) -> float | None:
    """Pull the persisted predicted conversion rate, clamped to ``[0, 1]``.

    Mirrors the assumption-postmortem extraction so the two endpoints see the
    same headline number from ``results_json``.
    """
    data = _coerce_results(results)
    for key in (
        "population_weighted_conversion",
        "conversion_rate",
        "mean_conversion_rate",
    ):
        value = _rate(data.get(key))
        if value is not None:
            return value
    raw_funnel = data.get("raw_funnel")
    if isinstance(raw_funnel, dict):
        value = _rate(raw_funnel.get("conversion_rate"))
        if value is not None:
            return value
    return None


def _confidence_label(mae: float, sample_count: int) -> str:
    """Bucket MAE into a confidence label, respecting minimum sample size."""
    if sample_count < MIN_OUTCOMES_FOR_RANGE:
        return LABEL_INSUFFICIENT_DATA
    if mae < WELL_CALIBRATED_MAX_MAE:
        return LABEL_WELL_CALIBRATED
    if mae < NEEDS_ATTENTION_MAX_MAE:
        return LABEL_NEEDS_ATTENTION
    return LABEL_POORLY_CALIBRATED


def _spread(mae: float, rmse: float, sample_count: int) -> float:
    """Compute the half-width of the prediction range."""
    if sample_count <= 0:
        return DEFAULT_SPREAD
    base = max(mae, rmse * RMSE_WEIGHT)
    multiplier = SMALL_SAMPLE_WIDENING if sample_count < SMALL_SAMPLE_COUNT else 1.0
    return min(MAX_SPREAD, max(MIN_SPREAD, base * multiplier))


def _clamp_range(predicted: float, spread: float) -> tuple[float, float]:
    """Clamp the range to ``[0, 1]``, preserving at least ``MIN_SPREAD`` width."""
    low = max(0.0, predicted - spread)
    high = min(1.0, predicted + spread)
    if high - low < MIN_SPREAD:
        if predicted < 0.5:
            high = min(1.0, low + MIN_SPREAD)
        else:
            low = max(0.0, high - MIN_SPREAD)
    return round(low, 6), round(high, 6)


def _narrative(
    predicted: float | None,
    raw_count: int,
    sample_count: int,
    mae: float,
    spread: float,
    low: float | None,
    high: float | None,
) -> str:
    if predicted is None:
        return (
            "No predicted conversion rate was found in this run, so no "
            "accuracy-adjusted range can be produced."
        )
    if raw_count > sample_count and sample_count < MIN_OUTCOMES_FOR_RANGE:
        return (
            f"Found {raw_count} outcome row(s), but only {sample_count} had a "
            "usable predicted/actual conversion pair; the "
            f"{predicted:.1%} prediction is shown with a conservative "
            f"±{spread:.1%} band until at least {MIN_OUTCOMES_FOR_RANGE} "
            "usable outcomes are recorded."
        )
    if sample_count < MIN_OUTCOMES_FOR_RANGE:
        return (
            f"No calibration data yet — the {predicted:.1%} prediction is shown "
            f"with a conservative ±{spread:.1%} band until at least "
            f"{MIN_OUTCOMES_FOR_RANGE} outcomes are recorded."
        )
    if low is None or high is None:
        return (
            f"Across {sample_count} recorded outcome(s), the model's typical "
            "error is unknown, so no accuracy-adjusted range was produced."
        )
    return (
        f"Across {sample_count} recorded outcome(s), the model's typical error "
        f"is {mae:.1%}, so the realistic range for the predicted "
        f"{predicted:.1%} conversion is {low:.1%}–{high:.1%}."
    )


def _signal_severity(spread: float) -> str:
    if spread >= 0.10:
        return "critical"
    if spread >= 0.05:
        return "watch"
    return "ok"


def build_prediction_range(
    predicted_conversion_rate: float | None,
    pairs: list[tuple[float | None, float | None]],
    *,
    simulation_id: int,
    project_id: int,
    calibration_source: str = "none",
) -> dict:
    """Compose the accuracy-adjusted prediction-range payload.

    Args:
        predicted_conversion_rate: the run's headline predicted conversion
            rate, clamped to ``[0, 1]``, or ``None`` when unusable.
        pairs: historical ``(predicted, actual)`` outcome pairs.
        simulation_id: simulation primary key (echoed back).
        project_id: owning project primary key (echoed back).
        calibration_source: where the historical pairs came from —
            ``"project"``, ``"user"``, or ``"none"``.

    Returns:
        A dict matching :class:`PredictionRangeOut` with the calibrated
        low/high band, MAE/RMSE, confidence label, narrative, and key signals.
    """
    raw_count = len(pairs)
    usable_pairs: list[tuple[float, float]] = []
    for predicted, actual in pairs:
        pair = _usable_pair(predicted, actual)
        if pair is not None:
            usable_pairs.append(pair)

    aggregate = aggregate_outcomes(usable_pairs)
    sample_count = int(aggregate.get("mae_count", 0))
    mae = float(aggregate.get("mae", 0.0))
    rmse = float(aggregate.get("rmse", 0.0))
    label = (
        LABEL_INSUFFICIENT_DATA
        if predicted_conversion_rate is None
        else _confidence_label(mae, sample_count)
    )

    spread: float | None = None
    low: float | None = None
    high: float | None = None
    if predicted_conversion_rate is not None:
        spread = _spread(mae, rmse, sample_count)
        low, high = _clamp_range(predicted_conversion_rate, spread)

    narrative = _narrative(
        predicted_conversion_rate,
        raw_count,
        sample_count,
        mae,
        spread if spread is not None else DEFAULT_SPREAD,
        low,
        high,
    )

    range_severity = _signal_severity(spread if spread is not None else DEFAULT_SPREAD)
    if raw_count and sample_count == 0:
        mae_severity = "critical"
    elif sample_count < MIN_OUTCOMES_FOR_RANGE:
        mae_severity = "watch"
    elif mae >= 0.05:
        mae_severity = "critical"
    elif mae >= 0.02:
        mae_severity = "watch"
    else:
        mae_severity = "ok"

    if sample_count == 0:
        sample_severity = "critical"
    elif sample_count < MIN_OUTCOMES_FOR_RANGE:
        sample_severity = "watch"
    else:
        sample_severity = "ok"

    key_signals = [
        {
            "label": "predicted_conversion_rate",
            "value": (
                round(predicted_conversion_rate, 6)
                if predicted_conversion_rate is not None
                else None
            ),
            "severity": "ok",
        },
        {
            "label": "accuracy_adjusted_range",
            "value": (
                {"low": low, "high": high}
                if low is not None and high is not None
                else None
            ),
            "severity": range_severity,
        },
        {
            "label": "mean_absolute_error",
            "value": round(mae, 6),
            "severity": mae_severity,
        },
        {
            "label": "rmse",
            "value": round(rmse, 6),
            "severity": "watch" if rmse >= 0.05 else "ok",
        },
        {
            "label": "calibration_sample_count",
            "value": sample_count,
            "severity": sample_severity,
        },
        {
            "label": "calibration_source",
            "value": calibration_source,
            "severity": "info",
        },
        {
            "label": "confidence_label",
            "value": label,
            "severity": (
                "ok"
                if label == LABEL_WELL_CALIBRATED
                else "watch"
                if label == LABEL_NEEDS_ATTENTION or label == LABEL_INSUFFICIENT_DATA
                else "critical"
            ),
        },
    ]

    return {
        "simulation_id": simulation_id,
        "project_id": project_id,
        "status": "COMPLETED",
        "predicted_conversion_rate": (
            round(predicted_conversion_rate, 6)
            if predicted_conversion_rate is not None
            else None
        ),
        "low": low,
        "high": high,
        "spread": round(spread, 6) if spread is not None else None,
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "calibration_sample_count": sample_count,
        "calibration_source": calibration_source,
        "confidence_label": label,
        "narrative": narrative,
        "key_signals": key_signals,
        "meta": {
            "min_outcomes_for_range": MIN_OUTCOMES_FOR_RANGE,
            "small_sample_count": SMALL_SAMPLE_COUNT,
            "max_spread": MAX_SPREAD,
            "raw_pairs_supplied": raw_count,
            "usable_pairs_used": sample_count,
        },
    }


__all__ = [
    "DEFAULT_SPREAD",
    "MAX_SPREAD",
    "MIN_OUTCOMES_FOR_RANGE",
    "MIN_SPREAD",
    "RMSE_WEIGHT",
    "SMALL_SAMPLE_COUNT",
    "SMALL_SAMPLE_WIDENING",
    "build_prediction_range",
    "extract_predicted_conversion",
]
