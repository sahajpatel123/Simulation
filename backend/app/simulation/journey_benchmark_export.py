"""CSV/JSON export helpers for the journey-benchmark payload.

The route layer in ``app/api/v1/simulations.py`` already builds the benchmark
payload through :func:`build_journey_benchmark`. This module renders that same
payload as a spreadsheet-friendly CSV (default) or an indented JSON document so
founders can bring their portfolio/category benchmark comparison into
Sheets/Excel, a pitch doc, or a machine pipeline without writing a parser.

The CSV follows the same multi-section convention as the journey-analytics
export: an optional metadata block, the current simulation's funnel summary,
the cohort distribution, a per-stage leak comparison, the founder-facing
insights, and a meta section. Missing or malformed rows degrade to blanks
instead of crashing the export, and every cell is guarded against spreadsheet
formula injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.journey_benchmark import LEAK_STAGE_ORDER

FORMAT_VERSION = "1"


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_text(value: Any) -> str:
    """Render one value as text, normalising ``None`` and booleans."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _safe_float(value: Any) -> float:
    """Parse a finite float, defaulting to ``0.0`` for unusable values."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _safe_int(value: Any) -> int:
    """Parse a finite integer, defaulting to ``0`` for unusable values."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if math.isfinite(parsed) else 0


def _safe_csv_cell(value: Any) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value.lstrip()[:1] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not isinstance(metadata, dict) or not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "simulation_id",
        "project_id",
        "scope",
        "category",
        "format_version",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def journey_benchmark_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-benchmark payload as a multi-section CSV string."""
    data = _as_dict(payload)
    current = data.get("current") or {}
    distribution = data.get("distribution") or {}
    if not isinstance(current, dict):
        current = {}
    if not isinstance(distribution, dict):
        distribution = {}

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Current funnel summary.
    _write_row(writer, ["section", "Current Funnel"])
    _write_row(writer, ["key", "value"])
    for key in (
        "purchase_probability",
        "abandon_probability",
        "expected_steps_to_absorb",
        "expected_revisits",
    ):
        _write_row(writer, [key, _safe_float(current.get(key))])
    _write_row(
        writer,
        ["primary_exit_stage", _safe_text(current.get("primary_exit_stage"))],
    )
    _write_row(writer, [])

    # Cohort distribution.
    _write_row(writer, ["section", "Cohort Distribution"])
    _write_row(writer, ["metric", "value"])
    for key in (
        "median_purchase_probability",
        "mean_purchase_probability",
        "p25_purchase_probability",
        "p75_purchase_probability",
        "min_purchase_probability",
        "max_purchase_probability",
        "median_expected_steps",
        "median_expected_revisits",
    ):
        _write_row(writer, [key, _safe_float(distribution.get(key))])
    _write_row(
        writer,
        [
            "most_common_primary_exit_stage",
            _safe_text(distribution.get("most_common_primary_exit_stage")),
        ],
    )
    _write_row(writer, ["cohort_size", _safe_int(data.get("cohort_size"))])
    _write_row(writer, ["percentile_rank", _safe_float(data.get("percentile_rank"))])
    _write_row(writer, [])

    # Per-stage leak comparison (current vs cohort median).
    _write_row(writer, ["section", "Stage Leak Comparison"])
    _write_row(
        writer,
        [
            "stage",
            "current_probability",
            "cohort_median_probability",
            "delta",
        ],
    )
    current_leaks = current.get("exit_stage_distribution") or {}
    median_leaks = distribution.get("stage_leak_medians") or {}
    if not isinstance(current_leaks, dict):
        current_leaks = {}
    if not isinstance(median_leaks, dict):
        median_leaks = {}
    for stage in LEAK_STAGE_ORDER:
        current_value = _safe_float(current_leaks.get(stage))
        median_value = _safe_float(median_leaks.get(stage))
        _write_row(
            writer,
            [
                stage,
                current_value,
                median_value,
                round(current_value - median_value, 6),
            ],
        )
    _write_row(writer, [])

    # Founder-facing insights.
    _write_row(writer, ["section", "Insights"])
    _write_row(writer, ["rank", "insight"])
    insights = data.get("insights") or []
    if not isinstance(insights, list):
        insights = []
    if insights:
        for rank, insight in enumerate(insights, start=1):
            _write_row(writer, [rank, _safe_text(insight)])
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Meta (cohort composition details).
    _write_row(writer, ["section", "Meta"])
    _write_row(writer, ["key", "value"])
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    for key in (
        "raw_completed_count",
        "skipped_without_journey_data",
        "sample_limit",
    ):
        _write_row(writer, [key, _safe_int(meta.get(key))])

    return buffer.getvalue()


def journey_benchmark_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-benchmark payload as an indented JSON document."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "journey_benchmark": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "journey_benchmark_to_csv",
    "journey_benchmark_to_json",
]
