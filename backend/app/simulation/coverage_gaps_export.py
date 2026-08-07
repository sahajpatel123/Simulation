"""CSV/JSON export helpers for the per-project coverage-gaps digest.

The route layer in ``app/api/v1/projects.py`` already builds the
coverage-gaps payload with :func:`build_coverage_gaps`; this module
renders that payload as a spreadsheet-friendly CSV so founders can
bring the "which assumption categories are missing?" analysis into
their planning tools.

The output uses the same lightweight multi-section CSV convention as
the sensitivity and calibration-health exports: an optional metadata
block, a one-row-per-key summary section, one row per covered /
missing category, the sensitivity breakdown, and the key-signal
list. Missing optional fields render as blanks rather than crashing
the export.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _value(value: Any) -> object:
    return "" if value is None else value


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving normal data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with formula-injection guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def coverage_gaps_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a coverage-gaps payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Coverage Gaps Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "project_id",
        "project_title",
        "covered_categories",
        "missing_categories",
        "sensitivity_breakdown",
        "covered_cluster_count",
        "missing_architect_count",
        "total_assumption_count",
        "narrative",
    )
    for key in summary_keys:
        _write_row(writer, [key, _value(data.get(key))])
    _write_row(writer, [])

    # Covered categories.
    _write_row(writer, ["section", "Covered Categories"])
    _write_row(writer, ["index", "category"])
    for index, category in enumerate(data.get("covered_categories") or [], start=1):
        _write_row(writer, [index, _value(category)])
    _write_row(writer, [])

    # Missing categories.
    _write_row(writer, ["section", "Missing Categories"])
    _write_row(writer, ["index", "category"])
    for index, category in enumerate(data.get("missing_categories") or [], start=1):
        _write_row(writer, [index, _value(category)])
    _write_row(writer, [])

    # Sensitivity breakdown.
    _write_row(writer, ["section", "Sensitivity Breakdown"])
    _write_row(writer, ["sensitivity", "count"])
    breakdown = data.get("sensitivity_breakdown") or {}
    if isinstance(breakdown, dict):
        for sensitivity in sorted(breakdown):
            _write_row(writer, [sensitivity, _value(breakdown[sensitivity])])
    _write_row(writer, [])

    # Key signals.
    _write_row(writer, ["section", "Key Signals"])
    _write_row(writer, ["label", "value", "severity", "display"])
    for signal in data.get("key_signals") or []:
        if not isinstance(signal, dict):
            continue
        _write_row(
            writer,
            [
                _value(signal.get("label")),
                _value(signal.get("value")),
                _value(signal.get("severity")),
                _value(signal.get("display")),
            ],
        )

    return buffer.getvalue()


def coverage_gaps_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a coverage-gaps payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "coverage_gaps": _as_dict(payload)},
        default=str,
        indent=2,
    )


__all__ = ["coverage_gaps_to_csv", "coverage_gaps_to_json"]
