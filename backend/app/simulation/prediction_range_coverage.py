"""Pure out-of-sample prediction-range coverage digest.

The single-run prediction-range endpoint
(``GET /simulations/{id}/prediction-range``) tells a founder how wide the
accuracy-adjusted band is, but nothing tells them whether those bands have
historically *contained reality*. This module answers that follow-up:

* For every project outcome with a usable predicted + actual conversion,
  rebuild the band exactly the way the live endpoint would have at that
  moment — using only outcome history available *before* the outcome was
  recorded, with the same project-first / user-pool fallback.
* Check whether the recorded actual landed inside ``[low, high]``.
* Roll the per-row checks up into a coverage rate, mean miss margin, worst
  miss, verdict, narrative, and dashboard key signals.

The module is pure-Python (no SQL, no I/O), so the full out-of-sample
behaviour is verifiable with plain dicts and no database.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.schemas.prediction_range import (
    LABEL_INSUFFICIENT_DATA,
)
from app.simulation.prediction_range import (
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range,
)

# The live prediction-range endpoint caps its calibration history at the 200
# most recent usable outcome pairs (``app.api.v1.simulations._query_outcome_pairs``).
# Keep the out-of-sample rebuild on the same budget so the digest measures the
# band a founder would actually have seen at the time.
MAX_HISTORY_PAIRS: int = 200

# Verdict labels — same wording family as the calibration digests.
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VERDICT_WELL_CALIBRATED: str = "WELL_CALIBRATED"
VERDICT_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
VERDICT_POORLY_CALIBRATED: str = "POORLY_CALIBRATED"

# A coverage verdict needs at least this many out-of-sample checks; fewer
# checks is directionally interesting but not a verdict.
MIN_EVALUATED_FOR_VERDICT: int = 3

# Coverage-rate bands. 80%+ of actuals inside the band = well calibrated;
# below 60% the band is materially missing reality.
WELL_CALIBRATED_MIN_COVERAGE: float = 0.80
NEEDS_ATTENTION_MIN_COVERAGE: float = 0.60

# Tolerance for "inside the band" — avoid float-rounding false misses.
_WITHIN_EPSILON: float = 1e-9

# Signal severity buckets — same convention as the other dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_rate(value: Any) -> float | None:
    """Coerce a conversion rate to a finite float in ``[0, 1]`` or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def _iso(value: Any) -> str | None:
    """Render a DB datetime (or string) as an ISO string, or ``None``."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _sort_key(row: dict[str, Any]) -> tuple[str, int]:
    """Stable sort key: created_at ascending, id ascending."""
    return (_iso(row.get("created_at")) or "", int(row.get("id") or 0))


def _usable_row(row: dict[str, Any]) -> tuple[float, float] | None:
    """Return ``(predicted, actual)`` when both sides are usable."""
    predicted = _safe_rate(row.get("predicted_conversion_rate"))
    actual = _safe_rate(row.get("actual_conversion_rate"))
    if predicted is None or actual is None:
        return None
    return predicted, actual


def _choose_history(
    earlier: list[dict[str, Any]],
    *,
    project_id: int,
) -> tuple[list[tuple[float, float]], str]:
    """Pick the calibration history + source exactly like the live route.

    Project-level pairs are preferred once at least
    :data:`MIN_OUTCOMES_FOR_RANGE` exist; otherwise the user pool (all owned
    project outcomes passed to the helper) is used, with any project pairs
    as the final fallback — mirroring
    ``app.api.v1.simulations._load_prediction_calibration_pairs``.
    """
    project_pairs = [
        pair
        for row in earlier
        if (pair := _usable_row(row)) is not None
        and int(row.get("project_id") or -1) == project_id
    ]
    user_pairs = [
        pair
        for row in earlier
        if (pair := _usable_row(row)) is not None
    ]
    if len(project_pairs) >= MIN_OUTCOMES_FOR_RANGE:
        return project_pairs[-MAX_HISTORY_PAIRS:], "project"
    if len(user_pairs) >= MIN_OUTCOMES_FOR_RANGE:
        return user_pairs[-MAX_HISTORY_PAIRS:], "user"
    if project_pairs:
        return project_pairs, "project"
    if user_pairs:
        return user_pairs, "user"
    return [], "none"


def _coverage_verdict(coverage_rate: float | None, evaluated: int) -> str:
    """Map the empirical coverage rate to a verdict label."""
    if coverage_rate is None or evaluated < MIN_EVALUATED_FOR_VERDICT:
        return VERDICT_INSUFFICIENT_DATA
    if coverage_rate >= WELL_CALIBRATED_MIN_COVERAGE:
        return VERDICT_WELL_CALIBRATED
    if coverage_rate >= NEEDS_ATTENTION_MIN_COVERAGE:
        return VERDICT_NEEDS_ATTENTION
    return VERDICT_POORLY_CALIBRATED


def _verdict_severity(verdict: str) -> str:
    if verdict == VERDICT_WELL_CALIBRATED:
        return SIGNAL_OK
    if verdict == VERDICT_NEEDS_ATTENTION:
        return SIGNAL_WATCH
    if verdict == VERDICT_POORLY_CALIBRATED:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def _narrative(
    *,
    verdict: str,
    total_project_outcomes: int,
    evaluated_runs: int,
    within_range_count: int,
    coverage_rate: float | None,
    worst_miss: dict[str, Any] | None,
) -> str:
    """Compose the one-paragraph founder narrative."""
    if total_project_outcomes == 0:
        return (
            "No founder outcomes with usable predictions yet — record "
            "outcomes against completed simulations to verify whether the "
            "accuracy-adjusted prediction bands contain actual conversion."
        )
    if evaluated_runs == 0:
        return (
            f"{total_project_outcomes} outcome(s) exist, but none had enough "
            f"earlier calibration history ({MIN_OUTCOMES_FOR_RANGE}+ pairs) "
            "to evaluate the prediction band out-of-sample."
        )
    if verdict == VERDICT_INSUFFICIENT_DATA:
        return (
            f"Only {evaluated_runs} run(s) could be evaluated out-of-sample; "
            f"record at least {MIN_EVALUATED_FOR_VERDICT} outcomes to get a "
            "band-coverage verdict."
        )

    pct = coverage_rate * 100.0 if coverage_rate is not None else 0.0
    if verdict == VERDICT_WELL_CALIBRATED:
        tail = (
            "The accuracy-adjusted bands are well calibrated — keep "
            "recording outcomes to maintain the track record."
        )
    elif verdict == VERDICT_NEEDS_ATTENTION:
        tail = (
            "The bands are directionally useful but miss too often — "
            "widen the band or tighten calibration before relying on the "
            "range."
        )
    else:
        tail = (
            "The bands rarely contained actual conversion — treat the "
            "ranges as rough bounds and prioritize calibration improvements."
        )

    sentences = [
        f"Across {evaluated_runs} out-of-sample run(s), the prediction band "
        f"contained actual conversion in {within_range_count} "
        f"({pct:.0f}%)."
    ]
    if worst_miss:
        sentences.append(
            f"Worst miss: sim {worst_miss.get('simulation_id') or '?'} with "
            f"actual {worst_miss.get('actual_conversion_rate', 0):.2%} "
            f"outside [{worst_miss.get('low', 0):.2%}, "
            f"{worst_miss.get('high', 0):.2%}]."
        )
    sentences.append(tail)
    return " ".join(sentences)


def build_prediction_range_coverage(
    *,
    project_id: int,
    rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the out-of-sample prediction-range coverage digest.

    Args:
        project_id: owning project primary key (echoed back and used to
            select project-scoped history).
        rows: all owned-project outcome row dicts (the target project plus
            any other owned projects used for the user-pool fallback). Each
            row must expose ``project_id``, ``predicted_conversion_rate``,
            ``actual_conversion_rate``; ``id``, ``simulation_id`` and
            ``created_at`` are optional but recommended for stable ordering
            and row metadata.
        generated_at: ISO timestamp echoed back; defaults to now UTC.

    Returns:
        A dict matching :class:`PredictionRangeCoverageOut`. Never raises:
        empty or malformed input produces a zeroed digest.
    """
    usable: list[dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        if _usable_row(raw) is None:
            continue
        usable.append(raw)
    usable.sort(key=_sort_key)

    evaluated_rows: list[dict[str, Any]] = []
    for index, row in enumerate(usable):
        if int(row.get("project_id") or -1) != project_id:
            continue
        earlier = usable[:index]
        history, source = _choose_history(
            earlier,
            project_id=project_id,
        )
        predicted = _safe_rate(row.get("predicted_conversion_rate"))
        actual = _safe_rate(row.get("actual_conversion_rate"))
        if predicted is None or actual is None:
            continue

        payload = build_prediction_range(
            predicted_conversion_rate=predicted,
            pairs=history,
            simulation_id=int(row.get("simulation_id") or 0),
            project_id=project_id,
            calibration_source=source,
        )
        low = payload.get("low")
        high = payload.get("high")
        history_count = int(payload.get("calibration_sample_count") or 0)
        evaluated = (
            history_count >= MIN_OUTCOMES_FOR_RANGE
            and low is not None
            and high is not None
        )
        within: bool | None = None
        margin: float | None = None
        if evaluated and low is not None and high is not None:
            within = (
                actual >= low - _WITHIN_EPSILON
                and actual <= high + _WITHIN_EPSILON
            )
            if within:
                margin = 0.0
            else:
                margin = min(abs(actual - low), abs(actual - high))

        evaluated_rows.append(
            {
                "simulation_id": (
                    int(row.get("simulation_id"))
                    if row.get("simulation_id") is not None
                    else None
                ),
                "project_id": project_id,
                "predicted_conversion_rate": predicted,
                "actual_conversion_rate": actual,
                "low": low,
                "high": high,
                "history_count": history_count,
                "calibration_source": source,
                "confidence_label": str(
                    payload.get("confidence_label")
                    or LABEL_INSUFFICIENT_DATA
                ),
                "within": within,
                "margin": round(margin, 6) if margin is not None else None,
                "evaluated": bool(evaluated),
                "created_at": _iso(row.get("created_at")),
            }
        )

    checked = [row for row in evaluated_rows if row["evaluated"]]
    within_count = sum(1 for row in checked if row["within"])
    evaluated_count = len(checked)
    coverage_rate = (
        round(within_count / evaluated_count, 6)
        if evaluated_count
        else None
    )
    miss_margins = [
        float(row["margin"])
        for row in checked
        if row["margin"] is not None and row["margin"] > 0.0
    ]
    mean_margin = (
        round(sum(miss_margins) / len(miss_margins), 6)
        if miss_margins
        else None
    )
    worst_miss = (
        max(checked, key=lambda row: float(row["margin"] or -1.0))
        if miss_margins
        else None
    )
    verdict = _coverage_verdict(coverage_rate, evaluated_count)

    key_signals: list[dict[str, Any]] = [
        {
            "label": "evaluated_runs",
            "value": evaluated_count,
            "severity": (
                SIGNAL_WATCH
                if evaluated_count == 0
                else SIGNAL_OK
            ),
            "display": f"{evaluated_count} out-of-sample band check(s)",
        }
    ]
    if coverage_rate is not None:
        key_signals.append(
            {
                "label": "coverage_rate",
                "value": coverage_rate,
                "severity": _verdict_severity(verdict),
                "display": (
                    f"Band contained actual conversion in "
                    f"{within_count}/{evaluated_count} "
                    f"({coverage_rate * 100.0:.0f}%)"
                ),
            }
        )
    if mean_margin is not None:
        key_signals.append(
            {
                "label": "mean_miss_margin",
                "value": mean_margin,
                "severity": (
                    SIGNAL_WATCH
                    if mean_margin >= 0.05
                    else SIGNAL_OK
                ),
                "display": f"Mean miss margin {mean_margin * 100.0:.2f}pp",
            }
        )
    if worst_miss:
        key_signals.append(
            {
                "label": "worst_miss_simulation",
                "value": worst_miss.get("simulation_id"),
                "severity": SIGNAL_CRITICAL,
                "display": (
                    f"Worst miss: sim {worst_miss.get('simulation_id') or '?'}"
                ),
            }
        )
    key_signals.append(
        {
            "label": "verdict",
            "value": verdict,
            "severity": _verdict_severity(verdict),
            "display": f"Band-coverage verdict: {verdict.replace('_', ' ').title()}",
        }
    )

    return {
        "project_id": project_id,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "total_project_outcomes": sum(
            1
            for row in usable
            if int(row.get("project_id") or -1) == project_id
        ),
        "evaluated_runs": evaluated_count,
        "within_range_count": within_count,
        "coverage_rate": coverage_rate,
        "mean_margin": mean_margin,
        "worst_miss": worst_miss,
        "verdict": verdict,
        "narrative": _narrative(
            verdict=verdict,
            total_project_outcomes=sum(
                1
                for row in usable
                if int(row.get("project_id") or -1) == project_id
            ),
            evaluated_runs=evaluated_count,
            within_range_count=within_count,
            coverage_rate=coverage_rate,
            worst_miss=worst_miss,
        ),
        "key_signals": key_signals,
        "rows": evaluated_rows,
    }


__all__ = [
    "MAX_HISTORY_PAIRS",
    "MIN_EVALUATED_FOR_VERDICT",
    "MIN_OUTCOMES_FOR_RANGE",
    "NEEDS_ATTENTION_MIN_COVERAGE",
    "SIGNAL_CRITICAL",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "VERDICT_INSUFFICIENT_DATA",
    "VERDICT_NEEDS_ATTENTION",
    "VERDICT_POORLY_CALIBRATED",
    "VERDICT_WELL_CALIBRATED",
    "WELL_CALIBRATED_MIN_COVERAGE",
    "build_prediction_range_coverage",
]
