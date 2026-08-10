"""Pure helpers for the admin platform audit log.

The per-user endpoint (``GET /users/me/audit-log``) answers "what did *my*
account just do?". This module backs the admin counterpart: an
operator-facing view over every mutating request across all users, with
filters (user, method, status, route substring, time window) and CSV/JSON
export for forensics and SIEM ingestion.

Everything here is pure (no DB, no I/O): the route layer owns the query and
hands plain row dicts to the serializers, while :func:`apply_admin_audit_filters`
returns SQLAlchemy clauses so the filtering logic can be unit-tested without
a live database.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.sql.elements import ColumnElement

from app.models.audit_log import ApiAuditLog

FORMAT_VERSION = "1"

# Only these methods are ever written by ``AuditLogMiddleware`` (GET/HEAD/
# OPTIONS are deliberately skipped), so a method filter outside this set is
# a caller bug rather than a legitimate query.
MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSV_HEADERS: list[str] = [
    "id",
    "user_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "ip_address",
    "request_id",
    "created_at",
]


def _utc(value: datetime | None) -> datetime | None:
    """Normalise a naive datetime to UTC so PG comparisons are unambiguous."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def apply_admin_audit_filters(
    *,
    user_id: int | None = None,
    method: str | None = None,
    status: int | None = None,
    route: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[ColumnElement[bool]]:
    """Build the WHERE clauses for an admin audit-log query.

    Each filter is applied only when provided, so an all-``None`` call
    returns an empty list (the route then scans newest-first, matching the
    per-user endpoint). ``method`` is case-normalised and validated against
    the methods the audit middleware actually writes; ``route`` uses a
    case-insensitive substring match with LIKE metacharacters escaped.
    """
    clauses: list[ColumnElement[bool]] = []

    if user_id is not None:
        clauses.append(ApiAuditLog.user_id == user_id)

    if method is not None:
        normalized = method.strip().upper()
        if normalized not in MUTATING_METHODS:
            raise ValueError(
                f"unsupported audit method {method!r}; expected one of "
                f"{sorted(MUTATING_METHODS)}"
            )
        clauses.append(ApiAuditLog.method == normalized)

    if status is not None:
        clauses.append(ApiAuditLog.status == status)

    if route is not None and route.strip():
        # ``autoescape`` turns LIKE wildcards in the user input into
        # literals, so a route containing ``%`` or ``_`` can never
        # broaden the match or turn this into a wildcard injection.
        clauses.append(ApiAuditLog.route.icontains(route.strip(), autoescape=True))

    since_utc = _utc(since)
    if since_utc is not None:
        clauses.append(ApiAuditLog.created_at >= since_utc)

    until_utc = _utc(until)
    if until_utc is not None:
        clauses.append(ApiAuditLog.created_at <= until_utc)

    return clauses


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
    # Excel/Sheets also treat values with leading whitespace as formulas once
    # they are trimmed, so guard the first non-whitespace character too.
    if isinstance(value, str) and value.lstrip()[:1] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "requested_by_user_id",
        "filter_user_id",
        "filter_method",
        "filter_status",
        "filter_route",
        "filter_since",
        "filter_until",
        "limit",
        "total",
        "format_version",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def admin_audit_log_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render admin audit-log row dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        writer.writerow([])

    _write_row(writer, CSV_HEADERS)
    for row in rows or []:
        _write_row(
            writer,
            [
                _text(row.get("id")),
                _text(row.get("user_id")),
                _text(row.get("method")),
                _text(row.get("route")),
                _text(row.get("status")),
                _text(row.get("duration_ms")),
                _text(row.get("ip_address")),
                _text(row.get("request_id")),
                _text(row.get("created_at")),
            ],
        )
    return buffer.getvalue()


def admin_audit_log_to_json(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render admin audit-log row dicts as an indented JSON document."""
    payload: dict[str, Any] = {"metadata": metadata or {}, "items": rows or []}
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n"


__all__ = [
    "CSV_HEADERS",
    "FORMAT_VERSION",
    "MUTATING_METHODS",
    "admin_audit_log_to_csv",
    "admin_audit_log_to_json",
    "apply_admin_audit_filters",
]
