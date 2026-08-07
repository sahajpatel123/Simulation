"""
Pure helper for exporting a project's assumption evidence as CSV.

The route layer pulls the evidence rows and hands them here as dicts;
this module stays deterministic and treats missing fields as empty
strings.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def evidence_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render evidence dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "id",
            "project_id",
            "assumption_id",
            "method",
            "result",
            "observed_metric",
            "notes",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("id")),
                _text(row.get("project_id")),
                _text(row.get("assumption_id")),
                _text(row.get("method")),
                _text(row.get("result")),
                _text(row.get("observed_metric")),
                _text(row.get("notes")),
                _text(row.get("created_at")),
            ]
        )
    return buffer.getvalue()


__all__ = ["evidence_to_csv"]
