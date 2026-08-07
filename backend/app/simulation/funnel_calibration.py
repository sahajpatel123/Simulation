"""Pure helpers for the per-project funnel calibration digest.

The dashboard already answers *"how trustable is the overall conversion
predict?"* via ``outcomes_digest``. This module answers a more specific
founder question: *"which funnel stage is the simulation mis-predicting?"*

It pairs the **predicted drop-off** that the simulation produced for each
forward funnel stage (``BROWSE`` / ``CONSIDER`` / ``DECIDE``) with the
**actual drop-off** founders recorded on their calibration-eligible
outcomes (rows with ``validated = true`` and ``learning_weight > 0``),
then reports:

* per-stage predicted / actual drop-off means,
* per-stage absolute error and bias direction,
* the single stage with the largest |predicted − actual| gap
  (the ``primary_mismatch_stage``),
* a domain-level recommendation for that stage,
* an overall conversion-bias verdict, and
* a one-paragraph narrative plus dashboard key-signals.

The helper is pure-Python (no SQL, no I/O). The route layer pulls the
``(results_json, actual_drop_map)`` pairs and hands them here.
"""
from __future__ import annotations

import math
from typing import Any

# Forward stages that founders can report actual drop-off for. These are the
# stages where a mismatch is actionable — PURCHASE / ABANDON / RETURN are not
# reported by founders today.
STAGES: tuple[str, ...] = ("BROWSE", "CONSIDER", "DECIDE")

# Cap on outcome rows we average. Beyond this the digest is informational
# only — recent outcomes are what matter.
MAX_PAIRS: int = 25

# |variance| bands (fraction of 1.0, e.g. 0.03 = 3 percentage points).
MAE_OK_THRESHOLD: float = 0.02
MAE_WATCH_THRESHOLD: float = 0.05

# Stage → (primary domain label, recommended architect names). Kept in sync
# with funnel_diagnosis.STAGE_DOMAIN_MAP so the calibration tile points at
# the same domains the bottleneck tile does.
STAGE_DOMAIN_MAP: dict[str, tuple[str, list[str]]] = {
    "BROWSE": (
        "ONBOARDING",
        ["OnboardingArchitect", "TrustArchitect", "ViralityArchitect"],
    ),
    "CONSIDER": (
        "TRUST",
        ["TrustArchitect", "CompetitiveDynamicsArchitect", "FeatureAdoptionArchitect"],
    ),
    "DECIDE": (
        "PRICING",
        ["PricingArchitect", "TrustArchitect", "PurchaseDecisionArchitect"],
    ),
}

# Signal severity buckets — keep aligned with the other dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: object, default: float | None = None) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _coerce_results(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def predicted_drop_rates_from_results(
    results: object,
) -> dict[str, float | None]:
    """Extract per-stage simulated drop-off from a results payload.

    Handles both the raw ``stage_metrics`` shape produced by
    ``FunnelResult`` and the aggregate ``stage_aggregations`` shape produced
    by ``ResultsAggregator``. Stages without a value are returned as ``None``.
    """
    payload = _coerce_results(results)
    raw_rows = payload.get("stage_metrics") or payload.get("stage_aggregations") or []
    if not isinstance(raw_rows, list):
        return {stage: None for stage in STAGES}

    per_stage: dict[str, float | None] = {stage: None for stage in STAGES}
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        stage = str(
            item.get("state") or item.get("stage") or ""
        ).upper().strip()
        if stage not in per_stage:
            continue
        drop = _safe_float(
            item.get("drop_off_rate", item.get("mean_drop_off_rate"))
        )
        per_stage[stage] = drop
    return per_stage


def _severity_for_gap(gap: float) -> str:
    """Map the per-stage |predicted − actual| gap to a severity label."""
    if gap >= MAE_WATCH_THRESHOLD:
        return SIGNAL_CRITICAL
    if gap >= MAE_OK_THRESHOLD:
        return SIGNAL_WATCH
    return SIGNAL_OK


def _direction_label(mean_bias: float) -> str:
    if abs(mean_bias) < 0.005:
        return "BALANCED"
    if mean_bias < 0:
        return "OVER_PREDICTING_DROP"
    return "UNDER_PREDICTING_DROP"


def _severity_for_bias(direction: str) -> str:
    if direction == "BALANCED":
        return SIGNAL_OK
    return SIGNAL_WATCH


def build_funnel_calibration_digest(
    pairs: list[
        tuple[object | None, dict[str, float | None] | None]
    ],
) -> dict[str, Any]:
    """Compose the funnel calibration digest.

    Args:
        pairs: list of ``(results_json, actual_drop_map)`` tuples, ordered
            newest-first. Each ``actual_drop_map`` should contain keys from
            ``STAGES`` with values in ``[0.0, 1.0]``; missing keys / ``None``
            values are skipped for that stage. Either side may be ``None``
            (missing); the row is still counted in ``outcome_count`` but
            contributes nothing to the numeric aggregates.

    Returns:
        Dict matching :class:`FunnelCalibrationDigestOut`.
    """
    outcome_count = len(pairs or [])

    # Per-stage sample collectors.
    predicted_by_stage: dict[str, list[float]] = {
        stage: [] for stage in STAGES
    }
    actual_by_stage: dict[str, list[float]] = {
        stage: [] for stage in STAGES
    }

    for results, actual_map in (pairs or [])[:MAX_PAIRS]:
        predicted_map = predicted_drop_rates_from_results(results)
        actual_map = actual_map or {}
        for stage in STAGES:
            predicted = predicted_map.get(stage)
            actual = _safe_float(actual_map.get(stage))
            if predicted is not None and actual is not None:
                predicted_by_stage[stage].append(predicted)
                actual_by_stage[stage].append(actual)

    stage_diagnostics: list[dict[str, Any]] = []
    primary_mismatch_stage: str | None = None
    primary_mismatch_gap: float = -1.0
    usable_count = 0

    for stage in STAGES:
        pred_rates = predicted_by_stage[stage]
        actual_rates = actual_by_stage[stage]
        sample_count = len(pred_rates)
        usable_count += sample_count

        if sample_count == 0:
            stage_diagnostics.append(
                {
                    "stage": stage,
                    "predicted_drop_off_rate": None,
                    "actual_drop_off_rate": None,
                    "sample_count": 0,
                    "mean_abs_gap": None,
                    "bias": None,
                    "direction": "INSUFFICIENT_DATA",
                    "severity": SIGNAL_WATCH,
                    "primary_domain": STAGE_DOMAIN_MAP[stage][0],
                    "recommended_architects": list(
                        STAGE_DOMAIN_MAP[stage][1]
                    ),
                }
            )
            continue

        mean_pred = sum(pred_rates) / sample_count
        mean_actual = sum(actual_rates) / sample_count
        mae = sum(
            abs(a - p) for p, a in zip(pred_rates, actual_rates)
        ) / sample_count
        mean_bias = sum(
            a - p for p, a in zip(pred_rates, actual_rates)
        ) / sample_count
        direction = _direction_label(mean_bias)

        stage_diagnostics.append(
            {
                "stage": stage,
                "predicted_drop_off_rate": round(mean_pred, 6),
                "actual_drop_off_rate": round(mean_actual, 6),
                "sample_count": sample_count,
                "mean_abs_gap": round(mae, 6),
                "bias": round(mean_bias, 6),
                "direction": direction,
                "severity": _severity_for_gap(mae),
                "primary_domain": STAGE_DOMAIN_MAP[stage][0],
                "recommended_architects": list(
                    STAGE_DOMAIN_MAP[stage][1]
                ),
            }
        )

        if mae > 0.0 and mae > primary_mismatch_gap:
            primary_mismatch_gap = mae
            primary_mismatch_stage = stage

    # Overall conversion-level bias across usable rows (any stage).
    all_bias: list[float] = []
    for stage in STAGES:
        for pred, actual in zip(
            predicted_by_stage[stage], actual_by_stage[stage]
        ):
            all_bias.append(actual - pred)
    if all_bias:
        mean_overall_bias = sum(all_bias) / len(all_bias)
        overall_direction = _direction_label(mean_overall_bias)
        overall_bias = round(mean_overall_bias, 6)
    else:
        overall_direction = "INSUFFICIENT_DATA"
        overall_bias = None

    mismatch_detail: dict[str, Any] | None = None
    if primary_mismatch_stage:
        detail = next(
            d for d in stage_diagnostics
            if d["stage"] == primary_mismatch_stage
        )
        mismatch_detail = {
            "stage": primary_mismatch_stage,
            "domain": detail["primary_domain"],
            "mean_abs_gap": detail["mean_abs_gap"],
            "direction": detail["direction"],
            "recommended_architects": detail["recommended_architects"],
        }

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict[str, Any]] = [
        {
            "label": "outcome_count",
            "value": outcome_count,
            "severity": (
                SIGNAL_WATCH if outcome_count == 0 else SIGNAL_OK
            ),
            "display": f"{outcome_count} outcome(s) recorded",
        }
    ]
    if usable_count > 0:
        key_signals.append(
            {
                "label": "usable_stage_pairs",
                "value": usable_count,
                "severity": SIGNAL_OK,
                "display": f"{usable_count} stage pair(s) usable",
            }
        )
    if mismatch_detail:
        key_signals.append(
            {
                "label": "primary_mismatch_stage",
                "value": mismatch_detail["stage"],
                "severity": _severity_for_gap(
                    float(mismatch_detail["mean_abs_gap"])
                ),
                "display": (
                    f"Primary mismatch: {mismatch_detail['stage'].lower()} "
                    f"({mismatch_detail['domain'].lower()})"
                ),
            }
        )
    if overall_direction != "INSUFFICIENT_DATA":
        key_signals.append(
            {
                "label": "funnel_bias",
                "value": overall_direction,
                "severity": _severity_for_bias(overall_direction),
                "display": (
                    "Simulation is "
                    f"{'over-predicting' if overall_direction == 'OVER_PREDICTING_DROP' else 'under-predicting'} "
                    "funnel drop-off"
                ),
            }
        )

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if outcome_count == 0:
        sentences.append(
            "No founder outcomes recorded yet — record outcomes "
            "to calibrate the funnel."
        )
    elif usable_count == 0:
        sentences.append(
            f"{outcome_count} outcome(s) recorded but none have both "
            "simulated and actual stage drop-off values."
        )
    elif mismatch_detail:
        sentences.append(
            f"Across {usable_count} usable stage pair(s), the biggest "
            f"prediction gap is at "
            f"{primary_mismatch_stage.lower()} "
            f"({mismatch_detail['domain'].lower()} domain)."
        )
    else:
        sentences.append(
            "No per-stage prediction gap was detected across the "
            "usable outcomes."
        )
    if usable_count > 0:
        if overall_direction == "OVER_PREDICTING_DROP":
            sentences.append(
                "The simulation over-predicts drop-off — actual users "
                "convert better than the funnel suggests."
            )
        elif overall_direction == "UNDER_PREDICTING_DROP":
            sentences.append(
                "The simulation under-predicts drop-off — real-world "
                "drop-off is worse than the funnel suggests."
            )
        else:
            sentences.append(
                "Overall funnel drop-off bias is balanced."
            )
    narrative = " ".join(sentences)

    return {
        "outcome_count": outcome_count,
        "usable_count": usable_count,
        "stages": stage_diagnostics,
        "primary_mismatch_stage": primary_mismatch_stage,
        "primary_mismatch": mismatch_detail,
        "funnel_bias": {
            "direction": overall_direction,
            "bias": overall_bias,
        },
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "STAGES",
    "MAX_PAIRS",
    "MAE_OK_THRESHOLD",
    "MAE_WATCH_THRESHOLD",
    "STAGE_DOMAIN_MAP",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "predicted_drop_rates_from_results",
    "build_funnel_calibration_digest",
]
