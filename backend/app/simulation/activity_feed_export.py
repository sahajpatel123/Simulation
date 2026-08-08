"""Pure helper for exporting a project's activity feed as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def activity_feed_to_csv(
    events: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render activity-feed events as a CSV table (one row per event)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["project_id", _text(metadata.get("project_id"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["type", "occurred_at", "ref_id", "title", "summary", "severity"])
    for event in events or []:
        writer.writerow(
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
