"""
Pure helpers for the cross-simulation outcomes digest endpoint.

The outcomes digest is the "calibration at scale" view: across N
simulations that have actual outcomes attached, how accurate were
the predictions?

The aggregation is intentionally narrow:

* ``mae`` — Mean Absolute Error of conversion rate (predicted -
  actual), in absolute terms (always non-negative).
* ``mape`` — Mean Absolute Percentage Error. A sim where we
  predicted 10% and actual was 9% contributes 10 % to the average.
  Sims with actual == 0 are excluded from MAPE so the aggregate
  doesn't blow up to infinity.
* ``rmse`` — Root Mean Squared Error (penalises outliers).
* ``outlier_count`` — how many pairs have absolute variance > 0.10
  (default). The threshold is configurable.
* ``direction_breakdown`` — ``{"over": N, "under": N, "exact": N}``.
  "over" means the model predicted higher than actual; "under" the
  inverse. "exact" covers pairs within a small epsilon (default 1e-6).
* ``per_pair`` — the raw (predicted, actual, variance) tuples so the
  UI can render a scatter plot.
* ``simulation_count`` — how many simulations contributed.
* ``with_predictions`` — how many pairs had a non-null predicted
  value (numerator of the aggregate denominators — useful so the UI
  can show "X of Y predictions were actionable").

The aggregate is built in Python (not SQL) because the dataset per
request is bounded by the batch cap (100 sims) and per-pair numerics
are O(1). One pass keeps the contract surface small.
"""
from __future__ import annotations

import math

# Default outlier threshold — absolute variance in conversion-rate
# terms. A 10pp gap is "noticeable" in the conversion-rate context
# (e.g. 8 % predicted vs 18 % actual is a 10pp gap that the founder
# would want to investigate).
DEFAULT_OUTLIER_THRESHOLD: float = 0.10
MIN_OUTLIER_THRESHOLD: float = 0.0
MAX_OUTLIER_THRESHOLD: float = 1.0

# Epsilon for "exact" match — anything below this absolute gap is
# treated as a no-error prediction. Keeps the direction_breakdown
# honest when both sides round to the same value.
_EXACT_EPSILON: float = 1e-6


def _safe_float(raw: object) -> float | None:
    """Coerce a value to a finite ``float`` or return ``None``.

    Used for the predicted / actual columns — a missing or
    non-numeric value means "we don't have a prediction for this
    sim" and must be skipped, not silently coerced to 0 (which
    would make the aggregate look like a perfect 0 % error).

    Non-finite values (``NaN`` / ``+inf`` / ``-inf``) are
    rejected as well: they parse as a number but corrupt every
    downstream aggregate (MAE, RMSE) — better to skip the pair
    than to let one bad input poison the whole rollup.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # ``bool`` is a subclass of ``int`` in Python; refuse booleans
        # so a stray True doesn't sneak into the average as 1.0.
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        # ``float("NaN")`` / ``float("inf")`` / overflow values all
        # land here — treat them as "missing" so the pair is counted
        # in ``simulation_count`` but excluded from MAE / MAPE / RMSE.
        return None
    return value


def aggregate_outcomes(
    pairs: list[tuple[float | None, float | None]],
    *,
    outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD,
) -> dict:
    """Aggregate predicted vs actual across N simulation outcomes.

    Args:
        pairs: list of ``(predicted, actual)`` tuples. ``None`` on
            either side means "missing" — the pair is included in the
            total count but excluded from MAE / MAPE / RMSE.
        outlier_threshold: absolute variance above which the pair is
            counted as an outlier. Default 0.10 (10pp).

    Returns:
        A dict matching the ``OutcomesDigestOut`` schema:

        * ``mae`` — mean absolute error (predicted - actual, |.|).
        * ``mape`` — mean absolute percentage error, computed only
          over pairs with actual != 0.
        * ``rmse`` — root mean squared error.
        * ``mae_count`` — number of pairs fed into MAE.
        * ``mape_count`` — number of pairs fed into MAPE.
        * ``outlier_count`` — pairs with |variance| > threshold.
        * ``direction_breakdown`` — ``{"over", "under", "exact"}``.
        * ``per_pair`` — list of per-simulation tuples (predicted,
          actual, variance, is_outlier).
        * ``simulation_count`` — total pairs in the input.
        * ``with_predictions`` — how many pairs had a non-null
          predicted value.
    """
    if outlier_threshold < MIN_OUTLIER_THRESHOLD:
        outlier_threshold = MIN_OUTLIER_THRESHOLD
    if outlier_threshold > MAX_OUTLIER_THRESHOLD:
        outlier_threshold = MAX_OUTLIER_THRESHOLD

    total = len(pairs)
    if total == 0:
        return {
            "mae": 0.0,
            "mape": 0.0,
            "rmse": 0.0,
            "mae_count": 0,
            "mape_count": 0,
            "outlier_count": 0,
            "direction_breakdown": {"over": 0, "under": 0, "exact": 0},
            "per_pair": [],
            "simulation_count": 0,
            "with_predictions": 0,
        }

    abs_errors: list[float] = []
    pct_errors: list[float] = []
    sq_errors: list[float] = []
    direction_breakdown = {"over": 0, "under": 0, "exact": 0}
    per_pair: list[dict] = []
    outlier_count = 0
    with_predictions = 0

    for predicted, actual in pairs:
        pred = _safe_float(predicted)
        act = _safe_float(actual)
        if pred is None or act is None:
            # Either side missing — skip this pair from the numeric
            # aggregates but keep it in the per_pair list (so the UI
            # can show "9 of 10 had predictions").
            per_pair.append({
                "predicted": pred,
                "actual": act,
                "variance": None,
                "is_outlier": False,
            })
            continue
        with_predictions += 1
        variance = pred - act
        abs_v = abs(variance)
        is_outlier = abs_v > outlier_threshold
        if is_outlier:
            outlier_count += 1
        if abs_v < _EXACT_EPSILON:
            direction_breakdown["exact"] += 1
        elif variance > 0:
            # Predicted > actual → model over-predicted.
            direction_breakdown["over"] += 1
        else:
            direction_breakdown["under"] += 1
        abs_errors.append(abs_v)
        sq_errors.append(variance * variance)
        if act != 0:
            pct_errors.append(abs_v / abs(act))
        per_pair.append({
            "predicted": pred,
            "actual": act,
            "variance": variance,
            "is_outlier": is_outlier,
        })

    mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
    rmse = (
        (sum(sq_errors) / len(sq_errors)) ** 0.5 if sq_errors else 0.0
    )
    mape = (
        sum(pct_errors) / len(pct_errors) if pct_errors else 0.0
    )
    return {
        "mae": mae,
        "mape": mape,
        "rmse": rmse,
        "mae_count": len(abs_errors),
        "mape_count": len(pct_errors),
        "outlier_count": outlier_count,
        "direction_breakdown": direction_breakdown,
        "per_pair": per_pair,
        "simulation_count": total,
        "with_predictions": with_predictions,
    }


def normalise_outlier_threshold(raw: float | None) -> float:
    """Coerce the outlier threshold query param into the allowed range.

    None / negative / over-1 values are clamped to the defaults / range
    bounds so a UI typo ("0.5%" instead of "0.5") never silently flips
    the outlier definition.
    """
    if raw is None:
        return DEFAULT_OUTLIER_THRESHOLD
    if raw < MIN_OUTLIER_THRESHOLD:
        return MIN_OUTLIER_THRESHOLD
    if raw > MAX_OUTLIER_THRESHOLD:
        return MAX_OUTLIER_THRESHOLD
    return raw


__all__ = [
    "DEFAULT_OUTLIER_THRESHOLD",
    "MIN_OUTLIER_THRESHOLD",
    "MAX_OUTLIER_THRESHOLD",
    "aggregate_outcomes",
    "normalise_outlier_threshold",
]