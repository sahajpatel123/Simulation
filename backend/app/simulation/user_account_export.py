"""
Pure helper for exporting a user's account info as CSV.

The route layer pulls the current user and hands the row here; this
module stays deterministic.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


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


def user_account_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a user account row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(
        writer,
        [
            "user_id",
            "email",
            "full_name",
            "tier",
            "subscription_tier",
            "simulations_used_this_month",
            "is_admin",
            "created_at",
        ],
    )
    write_row(
        writer,
        [
            _text(row.get("user_id")),
            _text(row.get("email")),
            _text(row.get("full_name")),
            _text(row.get("tier")),
            _text(row.get("subscription_tier")),
            _text(row.get("simulations_used_this_month")),
            _text(row.get("is_admin")),
            _text(row.get("created_at")),
        ],
    )
    return buffer.getvalue()


__all__ = ["user_account_to_csv"]
