"""
Pure helper for exporting a user's projects as CSV.

The route layer pulls the user's projects and hands them here as dicts;
this module stays deterministic.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


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
