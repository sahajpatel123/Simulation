"""Pure stage-level funnel calibration computations.

The funnel-calibration digest tells a founder *which* funnel stage the
simulation mis-predicts, but nothing fed that evidence back into the model.
This module closes the loop:

* For every validated founder outcome that reports a per-stage actual
  drop-off (``actual_drop_at_*_pct``), pair it with the drop-off the
  simulation predicted for the same stage.
* Convert each pair into a *pass-through ratio*
  ``(1 - actual_drop) / (1 - predicted_drop)`` — the factor by which the
  forward Markov transition would need to be multiplied for the simulation
  to have predicted the observed drop-off.
* Roll the per-outcome ratios up into a learning-weighted scalar per
  (product type, stage), gated by minimum sample and effective-sample
  counts, with the same confidence curve used by the other calibration
  layers.

The module is pure Python (no SQL, no I/O) so the whole computation is
verifiable with plain dicts.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from app.simulation.funnel_calibration import predicted_drop_rates_from_results

# Forward funnel stages founders can report actual drop-off for, mapped to
# the Markov transition each one calibrates. ARRIVE is deliberately absent:
# founders do not report arrival drop-off today.
STAGE_TRANSITIONS: dict[str, tuple[str, str]] = {
    "BROWSE": ("BROWSE", "CONSIDER"),
    "CONSIDER": ("CONSIDER", "DECIDE"),
    "DECIDE": ("DECIDE", "PURCHASE"),
}
STAGES: tuple[str, ...] = tuple(STAGE_TRANSITIONS)

# Gate: a stage needs at least this many usable outcomes and this much
# learning weight before a correction may move future simulations. The
# sample gate keeps a single founder from steering the model; the effective
# gate mirrors the other calibration layers' "evidence is earned" posture.
MIN_SAMPLE_COUNT: int = 3
MIN_EFFECTIVE_SAMPLE_COUNT: float = 5.0

# Same confidence curve as Layers 2/3 (eff / (eff + 30)).
CONFIDENCE_DENOMINATOR: float = 30.0

# Same scalar bounds the Conductor enforces for architect corrections, so a
# stage correction can never distort the funnel more than any other learned
# scalar.
MIN_CORRECTION_SCALAR: float = 0.5
MAX_CORRECTION_SCALAR: float = 2.0

# Corrections below this confidence are not loaded/applied.
MIN_CONFIDENCE_WEIGHT: float = 0.20

# Cap on outcome rows consumed per run; recent outcomes are what matter.
MAX_OUTCOMES: int = 200

# Sentinel cluster id for product-type-wide corrections.
CLUSTER_ALL: str = "ALL"

# Scope label written to the corrections table.
SCOPE_GLOBAL: str = "FUNNEL_STAGE_GLOBAL"

# Row-normalisation floor/ceiling used by the Markov builder.
PROBABILITY_FLOOR: float = 0.001
PROBABILITY_CEILING: float = 0.999


def _safe_rate(value: Any) -> float | None:
    """Coerce a drop-off rate to a finite float in ``[0.0, 1.0]``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def stage_to_transition(stage: str) -> tuple[str, str] | None:
    """Return the Markov transition calibrated by a funnel stage."""
    return STAGE_TRANSITIONS.get(str(stage).upper())


def transition_corrections(
    stage_corrections: Mapping[str, Any] | None,
) -> dict[tuple[str, str], float]:
    """Map a stage→scalar dict to a transition→scalar dict.

    Malformed stages, non-finite scalars, and out-of-bounds scalars are
    skipped so a corrupt correction row can never reach the Markov builder.
    """
    out: dict[tuple[str, str], float] = {}
    for raw_stage, raw_scalar in (stage_corrections or {}).items():
        transition = stage_to_transition(raw_stage)
        if transition is None:
            continue
        scalar = _safe_scalar(raw_scalar)
        if scalar is None:
            continue
        out[transition] = scalar
    return out


def _safe_scalar(value: Any) -> float | None:
    """Coerce a correction scalar and clamp it to the safe bounds."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(MIN_CORRECTION_SCALAR, min(MAX_CORRECTION_SCALAR, parsed))


def _usable_pair(
    predicted_drop: Any,
    actual_drop: Any,
) -> tuple[float, float] | None:
    """Return ``(predicted_drop, actual_drop)`` when both are usable.

    A predicted drop of exactly 1.0 is unusable: its pass-through rate is
    zero, so the ratio ``(1 - actual) / (1 - predicted)`` is undefined and
    no finite correction can be learned from the pair.
    """
    predicted = _safe_rate(predicted_drop)
    actual = _safe_rate(actual_drop)
    if predicted is None or actual is None or predicted >= 1.0:
        return None
    return predicted, actual


def compute_stage_corrections(
    pairs: list[Mapping[str, Any]],
    *,
    product_type: str,
) -> list[dict[str, Any]]:
    """Compute per-stage pass-through correction scalars from outcome pairs.

    Args:
        pairs: outcome rows ordered newest-first. Each row must expose
            ``predicted_drop_rates`` (dict stage → float | None) and
            ``actual_drops`` (dict stage → float | None); ``learning_weight``
            is optional and defaults to ``1.0`` when missing.
        product_type: canonical product-type string echoed into every row.

    Returns:
        One dict per stage that cleared the sample/effective-sample gates:
        ``stage``, ``from_state``, ``to_state``, ``product_type``,
        ``correction_scalar`` (pass-through multiplier), ``confidence_weight``,
        ``effective_sample_count``, ``sample_count``, ``mean_bias`` (weighted
        mean actual − predicted drop) and ``scope``.
    """
    corrections: list[dict[str, Any]] = []

    for stage in STAGES:
        usable: list[tuple[float, float, float]] = []
        for row in pairs or []:
            predicted = _safe_rate(
                (row.get("predicted_drop_rates") or {}).get(stage)
            )
            actual = _safe_rate((row.get("actual_drops") or {}).get(stage))
            pair = _usable_pair(predicted, actual)
            if pair is None:
                continue
            weight_raw = row.get("learning_weight")
            if weight_raw is None or isinstance(weight_raw, bool):
                weight = 1.0
            else:
                try:
                    parsed = float(weight_raw)
                except (TypeError, ValueError, OverflowError):
                    parsed = math.nan
                if not math.isfinite(parsed) or parsed <= 0.0:
                    continue
                weight = parsed
            usable.append((pair[0], pair[1], weight))

        sample_count = len(usable)
        effective_sample_count = sum(weight for _, _, weight in usable)
        if sample_count < MIN_SAMPLE_COUNT:
            continue
        if effective_sample_count < MIN_EFFECTIVE_SAMPLE_COUNT:
            continue

        weighted_ratio_sum = 0.0
        weighted_bias_sum = 0.0
        for predicted, actual, weight in usable:
            pass_through_ratio = (1.0 - actual) / (1.0 - predicted)
            weighted_ratio_sum += pass_through_ratio * weight
            weighted_bias_sum += (actual - predicted) * weight

        mean_ratio = weighted_ratio_sum / effective_sample_count
        mean_bias = weighted_bias_sum / effective_sample_count
        scalar = max(
            MIN_CORRECTION_SCALAR,
            min(MAX_CORRECTION_SCALAR, mean_ratio),
        )
        confidence = min(
            1.0,
            effective_sample_count
            / (effective_sample_count + CONFIDENCE_DENOMINATOR),
        )
        from_state, to_state = STAGE_TRANSITIONS[stage]
        corrections.append(
            {
                "stage": stage,
                "from_state": from_state,
                "to_state": to_state,
                "product_type": product_type,
                "correction_scalar": round(scalar, 6),
                "confidence_weight": round(confidence, 6),
                "effective_sample_count": round(effective_sample_count, 4),
                "sample_count": sample_count,
                "mean_bias": round(mean_bias, 6),
                "scope": SCOPE_GLOBAL,
            }
        )

    return corrections


def corrected_forward_probability(
    current: float,
    scalar: float,
) -> float:
    """Return a forward probability multiplied by a correction scalar."""
    try:
        parsed_scalar = float(scalar)
    except (TypeError, ValueError, OverflowError):
        return float(current)
    if not math.isfinite(parsed_scalar):
        return float(current)
    return max(
        PROBABILITY_FLOOR,
        min(PROBABILITY_CEILING, float(current) * parsed_scalar),
    )


def stage_corrections_to_scalar_map(
    corrections: list[Mapping[str, Any]] | None,
) -> dict[str, float]:
    """Collapse correction rows into a stage→scalar map for one run.

    Rows with confidence below :data:`MIN_CONFIDENCE_WEIGHT` or malformed
    scalars are skipped. If a stage appears more than once the highest
    confidence row wins (ties keep the first occurrence) — the same
    determinism the Conductor uses for architect corrections.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in corrections or []:
        if not isinstance(row, Mapping):
            continue
        stage = str(row.get("stage") or "").upper().strip()
        if stage not in STAGE_TRANSITIONS:
            continue
        confidence = _safe_rate(row.get("confidence_weight"))
        if confidence is None or confidence < MIN_CONFIDENCE_WEIGHT:
            continue
        scalar = _safe_scalar(row.get("correction_scalar"))
        if scalar is None:
            continue
        current = best.get(stage)
        if current is None or confidence > float(current.get("confidence_weight") or 0.0):
            best[stage] = {
                "stage": stage,
                "correction_scalar": scalar,
                "confidence_weight": confidence,
            }
    return {
        stage: float(item["correction_scalar"])
        for stage, item in best.items()
    }


__all__ = [
    "CLUSTER_ALL",
    "CONFIDENCE_DENOMINATOR",
    "MAX_CORRECTION_SCALAR",
    "MAX_OUTCOMES",
    "MIN_CONFIDENCE_WEIGHT",
    "MIN_CORRECTION_SCALAR",
    "MIN_EFFECTIVE_SAMPLE_COUNT",
    "MIN_SAMPLE_COUNT",
    "SCOPE_GLOBAL",
    "STAGES",
    "STAGE_TRANSITIONS",
    "compute_stage_corrections",
    "corrected_forward_probability",
    "predicted_drop_rates_from_results",
    "stage_corrections_to_scalar_map",
    "stage_to_transition",
    "transition_corrections",
]
