"""
Pure helper for exporting a project's core metadata as CSV.

The route layer pulls the project and hands the row here; this module
stays deterministic.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def project_meta_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project metadata row as a single-row CSV table."""
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
            "project_id",
            "title",
            "description",
            "status",
            "intake_mode",
            "is_archived",
            "created_at",
        ],
    )
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("title")),
            _text(row.get("description")),
            _text(row.get("status")),
            _text(row.get("intake_mode")),
            _text(row.get("is_archived")),
            _text(row.get("created_at")),
        ],
    )
    return buffer.getvalue()


__all__ = ["project_meta_to_csv"]
