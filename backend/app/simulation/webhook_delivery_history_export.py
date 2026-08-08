"""CSV/JSON export helpers for simulation webhook delivery history.

The route layer in ``app/api/v1/simulation_webhooks.py`` already lists recent
delivery attempts as JSON. This module renders the same rows as a
spreadsheet-friendly CSV (default) or an indented JSON document so operators
can bring the audit trail into Sheets/Excel, a SIEM, or a debugging workflow
without writing a parser.

Rows are sorted newest-first by ``delivered_at`` (then ``id``) so the export
matches the list endpoint and manual-retry flow. The JSON request body is
stored as a compact JSON string in CSV exports so every delivery attempt stays
reproducible from a single row.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

FORMAT_VERSION = "1"

CSV_HEADERS = [
    "id",
    "webhook_subscription_id",
    "simulation_id",
    "event_type",
    "status",
    "attempt_status",
    "http_status",
    "error",
    "conversion_rate",
    "request_body",
    "retry_count",
    "delivered_at",
    "created_at",
]


def _text(value: Any) -> str:
    """Render one value for CSV with datetimes and bools normalised."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, separators=(",", ":"))
    return str(value)


def _safe_csv_cell(value: Any) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _sort_key(row: dict[str, Any]) -> tuple[datetime, int]:
    """Newest-first sort using ``delivered_at`` then ``id``."""
    delivered = row.get("delivered_at")
    if isinstance(delivered, datetime):
        if delivered.tzinfo is None:
            delivered = delivered.replace(tzinfo=timezone.utc)
        else:
            delivered = delivered.astimezone(timezone.utc)
    elif delivered is not None:
        try:
            parsed = datetime.fromisoformat(str(delivered))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delivered = parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            delivered = datetime.min.replace(tzinfo=timezone.utc)
    else:
        delivered = datetime.min.replace(tzinfo=timezone.utc)
    return delivered, int(row.get("id") or 0)


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "project_id",
        "webhook_id",
        "limit",
        "total",
        "format_version",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def webhook_deliveries_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render webhook delivery dicts as a single CSV table, newest first."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        writer.writerow([_safe_csv_cell(key), _safe_csv_cell(value)])
    if metadata:
        writer.writerow([])

    writer.writerow(CSV_HEADERS)
    for row in sorted(rows or [], key=_sort_key, reverse=True):
        writer.writerow(
            [
                _safe_csv_cell(_text(row.get("id"))),
                _safe_csv_cell(_text(row.get("webhook_subscription_id"))),
                _safe_csv_cell(_text(row.get("simulation_id"))),
                _safe_csv_cell(_text(row.get("event_type"))),
                _safe_csv_cell(_text(row.get("status"))),
                _safe_csv_cell(_text(row.get("attempt_status"))),
                _safe_csv_cell(_text(row.get("http_status"))),
                _safe_csv_cell(_text(row.get("error"))),
                _safe_csv_cell(_text(row.get("conversion_rate"))),
                _safe_csv_cell(_text(row.get("request_body"))),
                _safe_csv_cell(_text(row.get("retry_count"))),
                _safe_csv_cell(_text(row.get("delivered_at"))),
                _safe_csv_cell(_text(row.get("created_at"))),
            ]
        )
    return buffer.getvalue()


def webhook_deliveries_to_json(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render webhook delivery dicts as an indented JSON document."""
    payload: dict[str, Any] = {"metadata": metadata or {}, "items": rows or []}
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n"


__all__ = [
    "CSV_HEADERS",
    "FORMAT_VERSION",
    "webhook_deliveries_to_csv",
    "webhook_deliveries_to_json",
]
