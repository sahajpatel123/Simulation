"""CSV/JSON export helpers for the real-world outcome peer benchmark.

The route layer in ``app/api/v1/outcomes.py`` already builds the benchmark
payload through :func:`build_outcome_benchmark`. This module renders that same
payload as a spreadsheet-friendly CSV (default) or an indented JSON document so
founders can drop their real-world peer ranking into Sheets/Excel, a pitch
deck, or a machine pipeline without writing a parser.

The CSV follows the same multi-section convention as the journey-benchmark
export: an optional metadata block, the project's current outcome, the peer
distribution, the ranking verdict, the founder-facing insights, and a meta
section. Missing or malformed rows degrade to blanks instead of crashing the
export, and every cell is guarded against spreadsheet formula injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

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


def _maybe_float(value: Any) -> float | str:
    """Parse a finite float, or return ``""`` for missing/unusable values.

    Numeric values that are absent (``None``) render as a blank cell so an
    export with no current outcome or no peers never claims a fake ``0.0``.
    """
    if value is None or isinstance(value, bool):
        return ""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed if math.isfinite(parsed) else ""


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
        "project_id",
        "category",
        "format_version",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _current_value(
    current: dict[str, Any] | None,
    key: str,
    *,
    numeric: bool = False,
) -> object:
    """Read one current-outcome field, blank when there is no current row."""
    if not current:
        return ""
    value = current.get(key)
    if numeric:
        return _maybe_float(value)
    return _safe_text(value)


def outcome_benchmark_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-benchmark payload as a multi-section CSV string."""
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

    # Current outcome (the project's most recent founder-reported launch).
    _write_row(writer, ["section", "Current Outcome"])
    _write_row(writer, ["key", "value"])
    for key in (
        "outcome_id",
        "simulation_id",
        "project_id",
        "days_since_launch",
    ):
        value = _safe_int(current.get(key)) if current else ""
        _write_row(writer, [key, value])
    actual = _current_value(current, "actual_conversion_rate", numeric=True)
    predicted = _current_value(current, "predicted_conversion_rate", numeric=True)
    _write_row(writer, ["actual_conversion_rate", actual])
    _write_row(writer, ["predicted_conversion_rate", predicted])
    conversion_delta = ""
    if isinstance(actual, float) and isinstance(predicted, float):
        conversion_delta = round(actual - predicted, 6)
    _write_row(writer, ["conversion_delta", conversion_delta])
    _write_row(
        writer,
        ["data_confidence", _current_value(current, "data_confidence")],
    )
    _write_row(writer, ["launched", _current_value(current, "launched")])
    _write_row(writer, ["recorded_at", _current_value(current, "recorded_at")])
    _write_row(writer, [])

    # Peer-outcome distribution.
    _write_row(writer, ["section", "Peer Distribution"])
    _write_row(writer, ["metric", "value"])
    _write_row(writer, ["peer_count", _safe_int(distribution.get("peer_count"))])
    for key in ("min", "p25", "median", "p75", "max", "mean"):
        _write_row(writer, [key, _maybe_float(distribution.get(key))])
    _write_row(writer, [])

    # Ranking verdict.
    _write_row(writer, ["section", "Ranking"])
    _write_row(writer, ["key", "value"])
    _write_row(writer, ["category", _safe_text(data.get("category"))])
    _write_row(
        writer,
        ["percentile_rank", _maybe_float(data.get("percentile_rank"))],
    )
    _write_row(writer, ["verdict", _safe_text(data.get("verdict"))])
    _write_row(
        writer,
        ["median_comparison", _safe_text(data.get("median_comparison"))],
    )
    _write_row(writer, ["narrative", _safe_text(data.get("narrative"))])
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

    # Meta (peer-cohort composition details).
    _write_row(writer, ["section", "Meta"])
    _write_row(writer, ["key", "value"])
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    for key in (
        "peers_scanned",
        "peers_usable",
        "peers_skipped_invalid",
        "peers_skipped_product_changed",
    ):
        _write_row(writer, [key, _safe_int(meta.get(key))])
    _write_row(writer, ["data_sufficient", _safe_text(meta.get("data_sufficient"))])
    _write_row(writer, ["benchmark_scope", _safe_text(meta.get("benchmark_scope"))])

    return buffer.getvalue()


def outcome_benchmark_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-benchmark payload as an indented JSON document."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "outcome_benchmark": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "outcome_benchmark_to_csv",
    "outcome_benchmark_to_json",
]
