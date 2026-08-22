"""Shared rendering primitives for the ``*_export`` modules.

Every exporter in this package repeats the same small helper set: coercing
Pydantic payloads to dicts, guarding CSV cells against spreadsheet formula
injection, keeping JSON strictly serialisable, and rendering Markdown table
cells.  Historically each exporter grew its own private copy and the copies
drifted (different formula-guard character sets, different ``None`` renderings).
This module is now the single source of truth.

The CSV formula guard is the *union* of every historical variant so migrating
an exporter onto :func:`safe_csv_cell` can only widen protection, never narrow
it.
"""
from __future__ import annotations

import math
from typing import Any

_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
_RAW_WHITESPACE_PREFIXES: tuple[str, ...] = ("\t", "\r", "\n")


def as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain mapping into a plain dictionary."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def text(value: Any) -> str:
    """Render a scalar for export without leaking Python ``None`` text."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def safe_float(value: Any) -> float:
    """Parse a finite float, falling back to ``0.0`` for anything unparseable."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Prefixes a quote before any string whose first non-space character could be
    interpreted as a formula by Excel/Sheets/LibreOffice, or which starts with a
    control whitespace character that some spreadsheets strip before evaluating.
    """
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped[:1] in _FORMULA_PREFIXES or value[:1] in _RAW_WHITESPACE_PREFIXES:
        return f"'{value}"
    return value


def write_row(writer: Any, row: list[object]) -> None:
    """Write one CSV row with the formula-injection guard on every cell."""
    writer.writerow([safe_csv_cell(value) for value in row])


def json_safe(value: Any) -> Any:
    """Replace non-finite numbers so strict JSON serialisation cannot fail."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def escape_md(value: Any) -> str:
    """Escape pipes and newlines so a cell cannot break a Markdown table."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_pct(value: Any) -> str:
    """Format a 0–1 float as a percentage, or a dash when absent."""
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return escape_md(value)
    return f"{f * 100:.1f}%"


def md_date(value: Any) -> str:
    """Format a timestamp as a date, passing strings through escaped."""
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
    return escape_md(value)


def md_bool(value: Any, none_text: str = "—") -> str:
    """Render a boolean as ``yes``/``no`` with a configurable ``None`` cell."""
    if value is None:
        return none_text
    return "yes" if value else "no"


def md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return md_bool(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return "—"
        return str(value)
    return escape_md(value)


__all__ = [
    "as_dict",
    "escape_md",
    "json_safe",
    "md_bool",
    "md_cell",
    "md_date",
    "md_pct",
    "safe_csv_cell",
    "safe_float",
    "text",
    "write_row",
]
