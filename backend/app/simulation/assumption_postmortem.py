"""
Pure assumption postmortem digest for a completed simulation with a
recorded founder outcome.

The simulation pipeline scores assumptions (``scored_assumption.py``),
uses them in the conductor, and persists a predicted conversion rate. The
founder-outcome layer stores the actual conversion rate after launch.
This module answers the missing cross-layer question: **which assumptions
did reality most likely invalidate?**

Logic:

* Predicted conversion comes from the simulation ``results_json``
  (``population_weighted_conversion`` -> ``conversion_rate``).
* Actual conversion comes from the closest founder outcome row (by
  ``simulation_id`` first, else the latest project outcome).
* Each assumption gets an ``invalidation_score``:

  ``sensitivity_weight × |predicted − actual|``

  where sensitivity weights are ``LOW=0.2``, ``MEDIUM=0.5``,
  ``HIGH=0.8``, ``CRITICAL=1.0``. A HIGH/CRITICAL assumption that was
  wrong gets flagged harder than a LOW one; a matching conversion
  produces a low score and a ``VALIDATED`` verdict.

* The digest verdict is ``INVALIDATED`` when the mean score is above the
  high threshold, ``MIXED`` when above the moderate threshold, and
  ``VALIDATED`` otherwise. With no usable outcome the payload returns
  ``INSUFFICIENT_DATA``.

No DB / I/O — the route layer supplies ``results``, the assumption rows,
and the optional outcome row. All arithmetic is deterministic.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.assumption_postmortem import (
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_INVALIDATED,
    VERDICT_MIXED,
    VERDICT_VALIDATED,
    AssumptionPostmortemItem,
    AssumptionPostmortemOut,
    AssumptionPostmortemSummary,
)

# Fraction of conversion-rate mismatch treated as signal. Full 100% of the
# gap would over-weight low-signal runs; a 60% discount keeps the ranking
# conservative when outcomes are ESTIMATED.
OUTCOME_CONFIDENCE_DISCOUNT: float = 0.6

SENSITIVITY_WEIGHTS: dict[str, float] = {
    "LOW": 0.2,
    "MEDIUM": 0.5,
    "HIGH": 0.8,
    "CRITICAL": 1.0,
}

# Mean invalidation-score thresholds for the digest-level verdict.
VERDICT_INVALIDATED_MIN: float = 0.35
VERDICT_MIXED_MIN: float = 0.15

MAX_TOP_INVALIDATED: int = 5


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _predicted_conversion(results: dict[str, Any]) -> float | None:
    """Pull the persisted predicted conversion rate, clamped to [0, 1]."""
    raw = results.get(
        "population_weighted_conversion",
        results.get("conversion_rate", results.get("mean_conversion_rate")),
    )
    if raw is None or isinstance(raw, bool):
        return None
    value = _safe_float(raw)
    return max(0.0, min(1.0, value))


def _sensitivity_weight(sensitivity: str | None) -> float:
    key = (sensitivity or "MEDIUM").strip().upper()
    return SENSITIVITY_WEIGHTS.get(key, SENSITIVITY_WEIGHTS["MEDIUM"])


def _sensitivity_value(sensitivity: str | None) -> str:
    key = (sensitivity or "MEDIUM").strip().upper()
    if key not in SENSITIVITY_WEIGHTS:
        return "MEDIUM"
    return key


def _outcome_source_label(outcome: dict[str, Any] | None) -> str:
    if not outcome:
        return "NONE"
    if outcome.get("simulation_id"):
        return "SIMULATION"
    return "LATEST_PROJECT"


def _verdict_for_score(score: float) -> str:
    if score >= VERDICT_INVALIDATED_MIN:
        return VERDICT_INVALIDATED
    if score >= VERDICT_MIXED_MIN:
        return VERDICT_MIXED
    return VERDICT_VALIDATED


def _reason(
    verdict: str,
    score: float,
    conversion_delta: float | None,
    sensitivity: str,
) -> str:
    if verdict == VERDICT_INVALIDATED:
        return (
            f"Reality diverged from the {sensitivity}-sensitivity "
            "assumption (conversion gap "
            f"{abs(conversion_delta or 0.0):.1%})."
        )
    if verdict == VERDICT_MIXED:
        return (
            f"Partially inconsistent with observed conversion "
            f"(delta {conversion_delta or 0.0:+.1%})."
        )
    if verdict == VERDICT_VALIDATED:
        return (
            f"Observed conversion is consistent with this "
            f"{sensitivity}-sensitivity assumption."
        )
    return "No usable outcome to compare against."


def _digest_verdict(items: list[AssumptionPostmortemItem]) -> str:
    if not items:
        return VERDICT_INSUFFICIENT_DATA
    mean_score = sum(item.invalidation_score for item in items) / len(items)
    if mean_score >= VERDICT_INVALIDATED_MIN:
        return VERDICT_INVALIDATED
    if mean_score >= VERDICT_MIXED_MIN:
        return VERDICT_MIXED
    return VERDICT_VALIDATED


def build_assumption_postmortem(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    assumptions: list[dict[str, Any]] | None = None,
    outcome: dict[str, Any] | None = None,
    outcome_confidence: str | None = None,
) -> AssumptionPostmortemOut:
    """Compose the assumption-postmortem payload.

    Args:
        results: simulation ``results_json`` (dict or JSON string).
        simulation_id: simulation primary key (echoed back).
        project_id: owning project primary key (echoed back).
        status: simulation status string.
        assumptions: list of assumption row dicts with ``id``, ``text``,
            ``category``, ``sensitivity``, ``impact_score``. Missing /
            malformed rows are skipped.
        outcome: optional founder outcome row dict with
            ``actual_conversion_rate`` and optionally ``simulation_id``.
        outcome_confidence: ``EXACT`` / ``ESTIMATED`` / ``ROUGH`` (used to
            discount the conversion gap; defaults to ``ESTIMATED``).
    """
    data = _coerce_results(results)
    predicted = _predicted_conversion(data)

    actual: float | None = None
    outcome_source = _outcome_source_label(outcome)
    if outcome:
        raw_actual = outcome.get("actual_conversion_rate")
        value = _safe_float(raw_actual)
        if value > 0.0:
            actual = max(0.0, min(1.0, value))

    conversion_delta: float | None = None
    if predicted is not None and actual is not None:
        conversion_delta = round(predicted - actual, 6)

    usable_actual = actual is not None
    confidence = (outcome_confidence or "ESTIMATED").strip().upper()
    discount = OUTCOME_CONFIDENCE_DISCOUNT
    if confidence == "EXACT":
        discount = 1.0
    elif confidence == "ROUGH":
        discount = 0.35

    items: list[AssumptionPostmortemItem] = []
    for raw in assumptions or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue

        sensitivity = _sensitivity_value(raw.get("sensitivity"))
        impact = max(0.0, _safe_float(raw.get("impact_score")))

        if not usable_actual or predicted is None:
            items.append(
                AssumptionPostmortemItem(
                    assumption_id=raw.get("id"),
                    text=text,
                    category=(
                        str(raw.get("category"))
                        if raw.get("category") is not None
                        else None
                    ),
                    sensitivity=sensitivity,
                    impact_score=round(impact, 4),
                    invalidation_score=0.0,
                    verdict=VERDICT_INSUFFICIENT_DATA,
                    reason=_reason(
                        VERDICT_INSUFFICIENT_DATA,
                        0.0,
                        conversion_delta,
                        sensitivity,
                    ),
                )
            )
            continue

        gap = abs(conversion_delta or 0.0)
        score = min(
            1.0,
            max(
                0.0,
                _sensitivity_weight(sensitivity) * gap * discount * 10.0,
            ),
        )
        # Impact score nudges the ranking within the same sensitivity band,
        # never above the gap-driven score for a low-impact assumption.
        score = min(1.0, score + (impact / 10.0) * 0.05)
        verdict = _verdict_for_score(score)
        items.append(
            AssumptionPostmortemItem(
                assumption_id=raw.get("id"),
                text=text,
                category=(
                    str(raw.get("category"))
                    if raw.get("category") is not None
                    else None
                ),
                sensitivity=sensitivity,
                impact_score=round(impact, 4),
                invalidation_score=round(score, 6),
                verdict=verdict,
                reason=_reason(
                    verdict,
                    score,
                    conversion_delta,
                    sensitivity,
                ),
            )
        )

    items.sort(
        key=lambda item: (
            item.invalidation_score,
            item.impact_score,
            -len(item.text),
        ),
        reverse=True,
    )
    top = items[:MAX_TOP_INVALIDATED]

    verdict = (
        _digest_verdict(items)
        if usable_actual and predicted is not None
        else VERDICT_INSUFFICIENT_DATA
    )

    return AssumptionPostmortemOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        predicted_conversion_rate=predicted,
        actual_conversion_rate=actual,
        conversion_delta=conversion_delta,
        outcome_source=outcome_source,
        verdict=verdict,
        summary=AssumptionPostmortemSummary(
            total_assumptions=len(items),
            invalidated_count=sum(
                1 for item in items if item.verdict == VERDICT_INVALIDATED
            ),
            validated_count=sum(
                1 for item in items if item.verdict == VERDICT_VALIDATED
            ),
            insufficient_count=sum(
                1 for item in items if item.verdict == VERDICT_INSUFFICIENT_DATA
            ),
            top_invalidated=top,
        ),
        meta={
            "outcome_confidence": confidence,
            "outcome_confidence_discount": round(discount, 2),
            "max_top_invalidated": MAX_TOP_INVALIDATED,
            "verdict_thresholds": {
                "invalidated_min": VERDICT_INVALIDATED_MIN,
                "mixed_min": VERDICT_MIXED_MIN,
            },
        },
    )


__all__ = ["build_assumption_postmortem"]
