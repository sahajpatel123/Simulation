"""CSV/JSON export helpers for the per-project health scorecard.

The route layer in ``app/api/v1/projects.py`` already builds the
per-project health payload with :func:`build_project_health`; this module
renders that payload as a spreadsheet-friendly CSV so founders can bring
the "is this specific project in good shape?" score into planning tools,
retrospectives, or stakeholder updates.

The output uses the same lightweight multi-section CSV convention as the
sensitivity, coverage-gaps, and calibration-health exports: an optional
metadata block, a one-row-per-key summary section, a per-component score
breakdown table, and the key-signal list. Missing optional fields render
as blanks rather than crashing the export.
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


def _breakdown_cell(breakdown: Any) -> str:
    """Render the score breakdown as a compact ``component=points`` cell."""
    if not isinstance(breakdown, dict) or not breakdown:
        return ""
    return "; ".join(
        f"{key}={_value(value)}"
        for key, value in sorted(breakdown.items())
    )


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


def project_health_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project-health payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Project Health Summary"])
    _write_row(writer, ["key", "value"])
    for key in (
        "project_health_score",
        "verdict",
        "score_breakdown",
        "narrative",
    ):
        if key == "score_breakdown":
            _write_row(writer, [key, _breakdown_cell(data.get(key))])
        else:
            _write_row(writer, [key, _value(data.get(key))])
    _write_row(writer, [])

    # Score breakdown.
    _write_row(writer, ["section", "Score Breakdown"])
    _write_row(writer, ["component", "points"])
    breakdown = data.get("score_breakdown") or {}
    if isinstance(breakdown, dict) and breakdown:
        for component in sorted(breakdown):
            _write_row(writer, [component, _value(breakdown[component])])
    else:
        _write_row(writer, ["", ""])
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


def project_health_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project-health payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "project_health": _as_dict(payload)},
        default=str,
        indent=2,
    )


__all__ = ["project_health_to_csv", "project_health_to_json"]
