"""CSV/JSON export helpers for the per-project risk register.

The route layer in ``app/api/v1/projects.py`` already builds the risk
register payload with :func:`build_risk_register`; this module renders that
payload as a spreadsheet-friendly CSV (or an indented JSON document) so
founders can bring the ranked risk list, severity/source breakdowns and
key signals into their planning or audit tools.

The CSV follows the same lightweight multi-section convention as the
founder-action-plan and project-health exports: an optional metadata block,
a one-row-per-key summary section, severity/source breakdown tables, one row
per risk, and a key-signal table. Missing optional fields render as blanks
rather than crashing the export. The JSON export emits UTF-8 with
``ensure_ascii=False`` and a trailing newline so non-Latin titles,
descriptions, and emoji round-trip cleanly into spreadsheets and audit
pipelines.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.simulation.export_utils import write_row


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "project_id",
        "user_id",
        "format_version",
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
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas. The guard also
    catches formula characters hidden after leading whitespace, which Excel
    still interprets as formulas.
    """
    if isinstance(value, str):
        stripped = value.lstrip()
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") or (
            stripped[:1] in ("=", "+", "-", "@", "\t", "\r") and stripped != value
        ):
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
    write_row(writer, [_safe_csv_cell(value) for value in row])


def risk_register_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a risk register payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Risk Register Summary"])
    _write_row(writer, ["key", "value"])
    for key in (
        "project_id",
        "generated_at",
        "total_risks",
        "top_risk_count",
        "overall_risk_level",
        "top_risk_score",
        "narrative",
    ):
        _write_row(writer, [key, _value(data.get(key))])
    _write_row(writer, [])

    # Severity breakdown.
    _write_row(writer, ["section", "Severity Breakdown"])
    _write_row(writer, ["severity", "count"])
    breakdown = _as_dict(data.get("severity_breakdown"))
    if breakdown:
        for severity in sorted(breakdown):
            _write_row(writer, [severity, _value(breakdown[severity])])
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Source breakdown.
    _write_row(writer, ["section", "Source Breakdown"])
    _write_row(writer, ["source", "count"])
    source_breakdown = _as_dict(data.get("source_breakdown"))
    if source_breakdown:
        for source in sorted(source_breakdown):
            _write_row(
                writer,
                [source, _value(source_breakdown[source])],
            )
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Ranked risks.
    _write_row(writer, ["section", "Risks"])
    risk_keys = (
        "id",
        "source",
        "category",
        "title",
        "description",
        "severity",
        "probability",
        "impact",
        "risk_score",
        "recommended_action",
        "metric",
    )
    _write_row(writer, list(risk_keys))
    for raw_risk in data.get("risks") or []:
        risk = _as_dict(raw_risk) if raw_risk is not None else {}
        if not risk:
            continue
        _write_row(writer, [risk.get(key) for key in risk_keys])
    _write_row(writer, [])

    # Key signals.
    _write_row(writer, ["section", "Key Signals"])
    _write_row(writer, ["label", "value", "severity", "display"])
    signals = data.get("key_signals") or []
    if signals:
        for raw_signal in signals:
            signal = _as_dict(raw_signal) if raw_signal is not None else {}
            if not signal:
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
    else:
        _write_row(writer, ["", "", "", ""])

    return buffer.getvalue()


def risk_register_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a risk register payload as an indented JSON document."""
    return (
        json.dumps(
            {"metadata": metadata or {}, "risk_register": _as_dict(payload)},
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "risk_register_to_csv",
    "risk_register_to_json",
]
