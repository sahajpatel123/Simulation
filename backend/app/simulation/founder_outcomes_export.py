"""
Pure helper for exporting the calibration learning layer (``founder_outcomes``)
as CSV.

The route layer joins ``founder_outcomes`` to the owning simulation/project
and hands enriched row dicts here; this module stays deterministic and treats
missing or malformed fields as empty strings.
"""
from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION = "1"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def predicted_conversion_from_results(results: Any) -> float | None:
    """Best-effort predicted conversion rate from a simulation results payload."""
    payload = _coerce_results(results)
    for key in ("population_weighted_conversion", "conversion_rate", "mean_conversion_rate"):
        value = _safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _gap_pct(actual: Any, predicted: Any) -> str:
    actual_f = _safe_float(actual)
    predicted_f = _safe_float(predicted)
    if actual_f is None or predicted_f is None or predicted_f == 0.0:
        return ""
    return str(round((actual_f - predicted_f) / abs(predicted_f) * 100.0, 2))


def founder_outcomes_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render enriched founder-outcome dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", FORMAT_VERSION))])
        writer.writerow([])

    writer.writerow(
        [
            "id",
            "simulation_id",
            "project_id",
            "project_title",
            "created_at",
            "launched",
            "actual_conversion_rate",
            "predicted_conversion_rate",
            "gap_pct",
            "signal_quality_at_run",
            "days_since_launch",
            "data_confidence",
            "product_changed_since_sim",
            "pricing_changed",
            "target_market_changed",
            "validated",
            "learning_weight",
            "notes",
        ]
    )
    for row in rows:
        actual = row.get("actual_conversion_rate")
        predicted = row.get("predicted_conversion_rate")
        writer.writerow(
            [
                _text(row.get("id")),
                _text(row.get("simulation_id")),
                _text(row.get("project_id")),
                _text(row.get("project_title")),
                _text(row.get("created_at")),
                _text(row.get("launched")),
                _text(actual),
                _text(predicted),
                _gap_pct(actual, predicted),
                _text(row.get("signal_quality_at_run")),
                _text(row.get("days_since_launch")),
                _text(row.get("data_confidence")),
                _text(row.get("product_changed_since_sim")),
                _text(row.get("pricing_changed")),
                _text(row.get("target_market_changed")),
                _text(row.get("validated")),
                _text(row.get("learning_weight")),
                _text(row.get("notes")),
            ]
        )
    return buffer.getvalue()


__all__ = [
    "founder_outcomes_to_csv",
    "predicted_conversion_from_results",
]
