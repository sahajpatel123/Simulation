"""
Pure helper for exporting a project's competitive analysis as CSV.

The route layer pulls ``competitive_json`` from the project and hands
the competitor dicts here; this module stays deterministic and treats
missing fields as empty strings.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def competitors_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render competitor dicts as a single CSV table."""
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
            "name",
            "category",
            "pricing",
            "positioning",
            "target_segment",
            "features",
            "strengths",
            "weaknesses",
            "india_presence",
            "threat_level",
        ],
    )
    for row in rows:
        write_row(
            writer,
            [
                _text(row.get("name")),
                _text(row.get("category")),
                _text(row.get("pricing")),
                _text(row.get("positioning")),
                _text(row.get("target_segment")),
                _text(row.get("features")),
                _text(row.get("strengths")),
                _text(row.get("weaknesses")),
                _text(row.get("india_presence")),
                _text(row.get("threat_level")),
            ],
        )
    return buffer.getvalue()


def competitive_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a competitive-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "competitive_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("competitive_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["competitive_count_to_csv", "competitors_to_csv"]
