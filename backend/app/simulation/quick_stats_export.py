"""Pure helper for exporting a user's quick stats as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def quick_stats_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a quick-stats row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "user_id",
            "total_projects",
            "total_simulations",
            "total_decisions",
            "total_outcomes",
            "account_age_days",
        ]
    )
    writer.writerow(
        [
            _text(row.get("user_id")),
            _text(row.get("total_projects")),
            _text(row.get("total_simulations")),
            _text(row.get("total_decisions")),
            _text(row.get("total_outcomes")),
            _text(row.get("account_age_days")),
        ]
    )
    return buffer.getvalue()


__all__ = ["quick_stats_to_csv"]
