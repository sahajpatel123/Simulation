"""Pure helper for exporting a project's activity feed as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


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


def activity_feed_to_csv(
    events: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render activity-feed events as a CSV table (one row per event)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        _write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        _write_row(writer, ["project_id", _text(metadata.get("project_id"))])
        _write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        _write_row(
            writer,
            ["format_version", _text(metadata.get("format_version", "1"))],
        )
        _write_row(writer, [])

    _write_row(
        writer,
        ["type", "occurred_at", "ref_id", "title", "summary", "severity"],
    )
    for event in events or []:
        _write_row(
            writer,
            [
                _text(event.get("type")),
                _text(event.get("occurred_at")),
                _text(event.get("ref_id")),
                _text(event.get("title")),
                _text(event.get("summary")),
                _text(event.get("severity")),
            ]
        )
    return buffer.getvalue()


__all__ = ["activity_feed_to_csv"]
