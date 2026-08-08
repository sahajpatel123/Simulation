"""Pure helper for exporting a project's existing_product_description field as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(_safe_csv_cell(str(value)))


def _safe_csv_cell(value: str) -> str:
    """Neutralise spreadsheet formula injection while leaving normal text intact."""
    stripped = value.lstrip()
    if stripped[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def existing_product_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an existing-product row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "existing_product_description"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("existing_product_description")),
        ]
    )
    return buffer.getvalue()


__all__ = ["existing_product_to_csv"]
