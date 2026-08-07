"""CSV/JSON export helpers for the per-project recommendations digest.

The route layer in ``app/api/v1/projects.py`` already builds the
recommendations payload with :func:`build_recommendations_digest`;
this module renders that payload as a spreadsheet-friendly CSV so
founders can take TheCee's ranked "what should I change next?" list
into their planning tools.

The output follows the same lightweight multi-section CSV convention
as the sensitivity, coverage-gaps, and health-scorecard exports: an
optional metadata block, a one-row-per-key summary section, one row
per recommendation, and the key-signal list. Missing optional fields
render as blanks rather than crashing the export.
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


def _score_cell(value: object) -> object:
    """Render a nullable numeric score as a compact fixed-precision cell."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return _value(value)


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving normal data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas. The guard also
    catches formula characters hidden after leading whitespace, which Excel
    still interprets as formulas.
    """
    if isinstance(value, str):
        stripped = value.lstrip()
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") or (
            stripped[:1] in ("=", "+", "-", "@", "\t", "\r")
            and stripped != value
        ):
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with formula-injection guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def recommendations_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a recommendations-digest payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Recommendations Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "project_id",
        "recommendation_count",
        "critical_failure_count",
        "quick_win_count",
        "narrative",
    )
    for key in summary_keys:
        value = data.get(key)
        if key == "project_id" and value is None:
            # The digest payload does not carry its own project id;
            # fall back to the metadata block so the summary isn't
            # self-contradictory when metadata says project_id=7 but
            # the summary renders a blank.
            value = (metadata or {}).get("project_id")
        _write_row(writer, [key, _value(value)])
    _write_row(writer, [])

    # Recommendations table.
    _write_row(writer, ["section", "Top Recommendations"])
    _write_row(
        writer,
        [
            "rank",
            "source",
            "title",
            "severity",
            "impact_score",
            "priority_score",
            "description",
        ],
    )
    for rank, recommendation in enumerate(
        data.get("top_recommendations") or [],
        start=1,
    ):
        if not isinstance(recommendation, dict):
            continue
        _write_row(
            writer,
            [
                rank,
                _value(recommendation.get("source")),
                _value(recommendation.get("title")),
                _value(recommendation.get("severity")),
                _score_cell(recommendation.get("impact_score")),
                _score_cell(recommendation.get("priority_score")),
                _value(recommendation.get("description")),
            ],
        )
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


def recommendations_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a recommendations-digest payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "recommendations": _as_dict(payload)},
        default=str,
        indent=2,
    )


__all__ = ["recommendations_to_csv", "recommendations_to_json"]
