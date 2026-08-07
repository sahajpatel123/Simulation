"""Pure helper for exporting a project's precis_title_fingerprint field as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def precis_fingerprint_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a precis-fingerprint row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "precis_title_fingerprint"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("precis_title_fingerprint")),
        ]
    )
    return buffer.getvalue()


__all__ = ["precis_fingerprint_to_csv"]
