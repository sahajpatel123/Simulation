"""
Pure helper for exporting a project's founder brief as CSV.

The route layer pulls the brief fields from the project and hands them
here; this module stays deterministic.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def brief_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a founder brief dict as a single-row CSV table."""
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
            "brief_positioning",
            "brief_features_json",
            "brief_hook",
            "brief_completed_at",
        ]
    )
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("brief_positioning")),
            _text(row.get("brief_features_json")),
            _text(row.get("brief_hook")),
            _text(row.get("brief_completed_at")),
        ]
    )
    return buffer.getvalue()


__all__ = ["brief_to_csv"]
