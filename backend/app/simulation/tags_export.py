"""
Pure helper for exporting a project's tags as CSV.

The route layer pulls ``project.tags`` and hands the list here; this
module stays deterministic.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def tags_to_csv(
    tags: list[str],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a tag list as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["index", "tag"])
    for index, tag in enumerate(tags, start=1):
        writer.writerow([index, _text(tag)])
    return buffer.getvalue()


def tag_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a tag-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "tag_count"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("tag_count")),
        ]
    )
    return buffer.getvalue()


__all__ = ["tag_count_to_csv", "tags_to_csv"]
