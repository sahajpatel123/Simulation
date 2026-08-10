"""Pure helper for exporting a project's description field as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _safe_csv_cell(value: str) -> str:
    """Neutralise spreadsheet formula injection while leaving normal text intact."""
    stripped = value.lstrip()
    if stripped[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(_safe_csv_cell(str(value)))


def description_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a description row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "description"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("description")),
        ]
    )
    return buffer.getvalue()


def description_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a description count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "description_count"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("description_count")),
        ]
    )
    return buffer.getvalue()


__all__ = ["description_to_csv", "description_count_to_csv"]
