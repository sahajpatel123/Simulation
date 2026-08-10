"""Pure builder for the post-launch failure-attribution digest.

Founders already submit a ``primary_failure_reason`` when they record an
outcome through the rich outcome-feedback flow, but until now no product
surface used that signal. This module turns those self-reported reasons
into a digest: per reason, how many outcomes were attributed to it, what
share of attributed outcomes that represents, and how far the simulation's
prediction was from the real conversion when that reason was reported.

The builder is pure-Python (no DB, no I/O). The route layer loads
``founder_outcomes`` rows joined to their simulation and hands them here.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from app.simulation.founder_outcomes_export import (
    predicted_conversion_from_results,
)

# Cap on grouped reasons returned to the dashboard. Attribution is
# advisory and self-reported; a long tail of one-off phrasings is not
# useful to a founder, so we surface the most common reasons only.
MAX_REASONS: int = 20

# Signal severity buckets — kept aligned with the other dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Average |prediction error| (in percentage points) that turns a reason's
# rollup from "ok" to "watch" / "critical". Mirrors the outcome-digest
# MAE thresholds (2pp watch, 5pp critical) so one tile never tells the
# founder a different story than another.
ABS_VARIANCE_WATCH_PP: float = 2.0
ABS_VARIANCE_CRITICAL_PP: float = 5.0


def _normalise_reason(raw: Any) -> str | None:
    """Collapse whitespace / trim a reason, or return ``None`` when blank."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    return text[:50]


def _safe_rate(raw: Any) -> float | None:
    """Coerce a finite float in ``[0, 1]`` or return ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value


def _safe_non_negative(raw: Any) -> float | None:
    """Coerce a finite non-negative float or return ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0.0:
        return None
    return value


def _safe_bool(raw: Any) -> bool:
    """Coerce a truthy flag to a bool, tolerating raw-SQL mappings.

    Raw mappings return native booleans, but defensive string values
    (``"true"`` / ``"false"``) are handled explicitly so a serialized
    row can never flip a change flag by accident.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(raw, (int, float)):
        return math.isfinite(raw) and raw != 0
    return bool(raw)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _severity(avg_abs_variance_pp: float | None, sample_count: int) -> str:
    """Bucket a reason's average |prediction error| into a severity."""
    if sample_count <= 0 or avg_abs_variance_pp is None:
        return SIGNAL_WATCH
    if avg_abs_variance_pp >= ABS_VARIANCE_CRITICAL_PP:
        return SIGNAL_CRITICAL
    if avg_abs_variance_pp >= ABS_VARIANCE_WATCH_PP:
        return SIGNAL_WATCH
    return SIGNAL_OK


def _key_signals(
    total_outcomes: int,
    attributed_count: int,
    top_reason: str | None,
    top_share_pct: float | None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    signals.append({
        "label": "total_outcomes",
        "value": total_outcomes,
        "severity": SIGNAL_WATCH if total_outcomes == 0 else SIGNAL_OK,
        "display": f"{total_outcomes} outcome(s) recorded",
    })
    signals.append({
        "label": "attributed_count",
        "value": attributed_count,
        "severity": (
            SIGNAL_WATCH if attributed_count == 0 else SIGNAL_OK
        ),
        "display": (
            f"{attributed_count} outcome(s) with a failure reason"
            if attributed_count > 0
            else "No failure reasons reported yet"
        ),
    })
    if top_reason is not None:
        signals.append({
            "label": "top_failure_reason",
            "value": top_reason,
            "severity": SIGNAL_WATCH,
            "display": (
                f"Most reported reason: {top_reason} "
                f"({top_share_pct:.1f}% of attributed outcomes)"
                if top_share_pct is not None
                else f"Most reported reason: {top_reason}"
            ),
        })
    return signals


def build_failure_attribution(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
) -> dict[str, Any]:
    """Compose the failure-attribution payload from outcome rows.

    Args:
        rows: ``founder_outcomes`` rows enriched with the linked
            simulation's ``results_json`` (and optionally
            ``signal_quality`` / ``learning_weight`` /
            ``data_confidence`` / change flags). Missing or malformed
            rows are still counted in ``total_outcomes`` but contribute
            to ``unattributed_count`` when they carry no usable reason.
        project_id: owning project primary key (echoed back).

    Returns:
        A dict matching :class:`FailureAttributionOut`.
    """
    total_outcomes = len(rows or [])
    if not rows:
        return {
            "project_id": project_id,
            "total_outcomes": 0,
            "attributed_count": 0,
            "unattributed_count": 0,
            "top_reason": None,
            "reasons": [],
            "narrative": (
                "No founder outcomes recorded yet — failure attribution "
                "unlocks after you report how launch went."
            ),
            "key_signals": _key_signals(0, 0, None, None),
        }

    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "display": "",
            "count": 0,
            "abs_variance_pp": [],
            "signed_variance_pp": [],
            "signal_quality": [],
            "learning_weight": [],
            "days_since_launch": [],
            "data_confidence": defaultdict(int),
            "product_changed": 0,
            "pricing_changed": 0,
            "target_market_changed": 0,
        }
    )

    attributed_count = 0
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        reason = _normalise_reason(raw.get("primary_failure_reason"))
        if reason is None:
            continue
        attributed_count += 1

        key = reason.upper()
        bucket = buckets[key]
        if not bucket["display"]:
            bucket["display"] = reason
        bucket["count"] += 1

        actual = _safe_rate(raw.get("actual_conversion_rate"))
        predicted = _safe_rate(
            predicted_conversion_from_results(raw.get("results_json"))
        )
        if actual is not None and predicted is not None:
            delta_pp = (actual - predicted) * 100.0
            bucket["abs_variance_pp"].append(abs(delta_pp))
            bucket["signed_variance_pp"].append(delta_pp)

        quality = _safe_non_negative(raw.get("signal_quality_at_run"))
        if quality is not None:
            bucket["signal_quality"].append(min(quality, 1.0))

        weight = _safe_non_negative(raw.get("learning_weight"))
        if weight is not None:
            bucket["learning_weight"].append(min(weight, 1.0))

        days = _safe_non_negative(raw.get("days_since_launch"))
        if days is not None:
            bucket["days_since_launch"].append(days)

        confidence = str(raw.get("data_confidence") or "UNKNOWN").strip().upper()
        bucket["data_confidence"][confidence[:20]] += 1
        bucket["product_changed"] += 1 if _safe_bool(
            raw.get("product_changed_since_sim")
        ) else 0
        bucket["pricing_changed"] += 1 if _safe_bool(
            raw.get("pricing_changed")
        ) else 0
        bucket["target_market_changed"] += 1 if _safe_bool(
            raw.get("target_market_changed")
        ) else 0

    reasons: list[dict[str, Any]] = []
    for bucket in buckets.values():
        count = int(bucket["count"])
        avg_abs = _mean(bucket["abs_variance_pp"])
        reasons.append({
            "reason": str(bucket["display"])[:50],
            "count": count,
            "share_pct": round(
                count / attributed_count * 100.0, 2
            ) if attributed_count > 0 else 0.0,
            "avg_abs_variance_pp": (
                round(avg_abs, 4) if avg_abs is not None else None
            ),
            "avg_signed_variance_pp": (
                round(_mean(bucket["signed_variance_pp"]), 4)
                if bucket["signed_variance_pp"]
                else None
            ),
            "avg_signal_quality": _mean(bucket["signal_quality"]),
            "avg_learning_weight": _mean(bucket["learning_weight"]),
            "avg_days_since_launch": _mean(bucket["days_since_launch"]),
            "data_confidence_breakdown": dict(bucket["data_confidence"]),
            "product_changed_count": int(bucket["product_changed"]),
            "pricing_changed_count": int(bucket["pricing_changed"]),
            "target_market_changed_count": int(
                bucket["target_market_changed"]
            ),
            "severity": _severity(avg_abs, count),
        })

    reasons.sort(key=lambda item: (-item["count"], item["reason"]))
    reasons = reasons[:MAX_REASONS]
    top_reason: str | None = reasons[0]["reason"] if reasons else None
    top_share_pct: float | None = reasons[0]["share_pct"] if reasons else None

    # Narrative.
    if attributed_count == 0:
        narrative = (
            f"{total_outcomes} outcome(s) recorded, but none include a "
            "primary failure reason — add one on the next outcome-feedback "
            "submission to unlock attribution."
        )
    else:
        narrative = (
            f"Across {total_outcomes} recorded outcome(s), "
            f"{attributed_count} included a failure reason. "
            f"Most common: {top_reason} "
            f"({top_share_pct:.1f}% of attributed outcomes)."
        )
        worst = reasons[0]
        if worst.get("avg_abs_variance_pp") is not None:
            narrative += (
                f" When {worst['reason']} was reported, the simulation "
                f"missed by {worst['avg_abs_variance_pp']:.1f}pp on "
                "average."
            )

    return {
        "project_id": project_id,
        "total_outcomes": total_outcomes,
        "attributed_count": attributed_count,
        "unattributed_count": total_outcomes - attributed_count,
        "top_reason": top_reason,
        "reasons": reasons,
        "narrative": narrative,
        "key_signals": _key_signals(
            total_outcomes,
            attributed_count,
            top_reason,
            top_share_pct,
        ),
    }


__all__ = [
    "MAX_REASONS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "ABS_VARIANCE_WATCH_PP",
    "ABS_VARIANCE_CRITICAL_PP",
    "build_failure_attribution",
]
