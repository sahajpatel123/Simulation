"""
Pure helper for exporting a user's account info as CSV.

The route layer pulls the current user and hands the row here; this
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


def user_account_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a user account row as a single-row CSV table."""
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
            "email",
            "full_name",
            "tier",
            "subscription_tier",
            "simulations_used_this_month",
            "is_admin",
            "created_at",
        ]
    )
    writer.writerow(
        [
            _text(row.get("user_id")),
            _text(row.get("email")),
            _text(row.get("full_name")),
            _text(row.get("tier")),
            _text(row.get("subscription_tier")),
            _text(row.get("simulations_used_this_month")),
            _text(row.get("is_admin")),
            _text(row.get("created_at")),
        ]
    )
    return buffer.getvalue()


__all__ = ["user_account_to_csv"]
