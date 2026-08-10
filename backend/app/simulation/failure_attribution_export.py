"""CSV/JSON export helpers for the failure-attribution digest.

The route layer builds the digest through
:func:`build_failure_attribution`; this module renders that same payload
as a spreadsheet-friendly CSV (default) or an indented JSON document.
Every cell is guarded against spreadsheet formula injection and missing
or malformed values degrade to blanks instead of crashing the export.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION = "1"


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_text(value: Any) -> str:
    """Render one value as text, normalising ``None`` and booleans."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _maybe_float(value: Any) -> float | str:
    """Parse a finite float, or return ``""`` for missing/unusable values."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return ""
    return parsed if math.isfinite(parsed) else ""


def _safe_int(value: Any) -> int:
    """Parse a finite non-negative integer, defaulting to ``0``."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, float) and not value.is_integer():
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0


def _safe_csv_cell(value: Any) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value.lstrip()[:1] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def failure_attribution_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a failure-attribution payload as a multi-section CSV string."""
    data = _as_dict(payload)
    reasons = data.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        for key in (
            "generated_at",
            "user_id",
            "project_id",
            "format_version",
        ):
            value = metadata.get(key, "")
            _write_row(
                writer,
                [key, "" if value is None else str(value)],
            )
        _write_row(writer, [])

    # Summary.
    _write_row(writer, ["section", "Summary"])
    _write_row(writer, ["key", "value"])
    _write_row(writer, ["total_outcomes", _safe_int(data.get("total_outcomes"))])
    _write_row(
        writer,
        ["attributed_count", _safe_int(data.get("attributed_count"))],
    )
    _write_row(
        writer,
        ["unattributed_count", _safe_int(data.get("unattributed_count"))],
    )
    _write_row(writer, ["top_reason", _safe_text(data.get("top_reason"))])
    _write_row(writer, ["narrative", _safe_text(data.get("narrative"))])
    _write_row(writer, [])

    # Per-reason rows.
    _write_row(writer, ["section", "Reasons"])
    _write_row(
        writer,
        [
            "reason",
            "count",
            "share_pct",
            "avg_abs_variance_pp",
            "avg_signed_variance_pp",
            "avg_signal_quality",
            "avg_learning_weight",
            "avg_days_since_launch",
            "product_changed_count",
            "pricing_changed_count",
            "target_market_changed_count",
            "severity",
        ],
    )
    if reasons:
        for reason in reasons:
            if not isinstance(reason, dict):
                continue
            _write_row(
                writer,
                [
                    _safe_text(reason.get("reason")),
                    _safe_int(reason.get("count")),
                    _maybe_float(reason.get("share_pct")),
                    _maybe_float(reason.get("avg_abs_variance_pp")),
                    _maybe_float(reason.get("avg_signed_variance_pp")),
                    _maybe_float(reason.get("avg_signal_quality")),
                    _maybe_float(reason.get("avg_learning_weight")),
                    _maybe_float(reason.get("avg_days_since_launch")),
                    _safe_int(reason.get("product_changed_count")),
                    _safe_int(reason.get("pricing_changed_count")),
                    _safe_int(reason.get("target_market_changed_count")),
                    _safe_text(reason.get("severity")),
                ],
            )
    else:
        _write_row(writer, [""] * 12)

    return buffer.getvalue()


def failure_attribution_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a failure-attribution payload as an indented JSON document."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "failure_attribution": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "failure_attribution_to_csv",
    "failure_attribution_to_json",
]
