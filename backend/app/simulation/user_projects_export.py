"""
Pure helper for exporting a user's projects as CSV.

The route layer pulls the user's projects and hands them here as dicts;
this module stays deterministic.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving normal data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    (after stripping leading whitespace) are prefixed with a single quote so
    Excel, LibreOffice, and Google Sheets treat them as literal text rather
    than executable formulas. Leading whitespace is ignored during detection
    because spreadsheets often accept ``<space>=cmd()`` as a formula too.
    """
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(_safe_csv_cell(str(value)))


def user_projects_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render user project rows as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "project_id",
            "title",
            "status",
            "intake_mode",
            "is_archived",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("project_id")),
                _text(row.get("title")),
                _text(row.get("status")),
                _text(row.get("intake_mode")),
                _text(row.get("is_archived")),
                _text(row.get("created_at")),
            ]
        )
    return buffer.getvalue()


__all__ = ["user_projects_to_csv"]
