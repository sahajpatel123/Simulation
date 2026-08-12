"""CSV / JSON / Markdown export helpers for the outcome-feedback gaps digest.

The outcome-gaps endpoints (``GET /projects/{id}/outcome-gaps`` and
``GET /users/me/outcome-gaps``) tell a founder which completed simulation
runs still need real-world outcome feedback. This module renders the same
digest for download:

* CSV - a multi-section spreadsheet (metadata, summary, and one row per
  unscored simulation) so the founder can keep the feedback queue in Sheets
  or Excel;
* JSON - a strict, machine-readable envelope for BI pipelines and tools;
* Markdown - a concise founder-facing brief for docs, Notion, or a weekly
  review.

The module handles both the per-project and portfolio payloads: the
portfolio payload gains a ``project_id`` column / table column so every row
remains attributable. It stays pure and defensive: malformed rows,
non-finite numbers, missing fields, and empty payloads degrade to safe
defaults instead of raising, and CSV cells are guarded against spreadsheet
formula injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_PROJECT_SUMMARY_KEYS: tuple[str, ...] = (
    "total_completed",
    "scored",
    "unscored",
    "coverage_rate_pct",
    "learning_eligible_unscored",
    "oldest_unscored_age_days",
    "narrative",
)

_PORTFOLIO_SUMMARY_KEYS: tuple[str, ...] = (
    "project_count",
    "projects_with_gaps",
    "total_completed",
    "scored",
    "unscored",
    "coverage_rate_pct",
    "learning_eligible_unscored",
    "high_priority_unscored",
    "oldest_unscored_age_days",
    "narrative",
)

_ITEM_HEADERS: list[str] = [
    "simulation_id",
    "created_at",
    "age_days",
    "signal_quality",
    "predicted_conversion_rate",
    "product_type_detected",
    "primary_failure_domain",
    "has_results",
    "learning_eligible",
    "urgency",
    "recommendation",
]

_FORMULA_STARTERS: tuple[str, ...] = ("=", "+", "-", "@")
_CONTROL_STARTERS: tuple[str, ...] = ("\t", "\r", "\n")


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Coerce a value to a finite float, or ``default`` when unusable."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_rate(value: Any) -> float | None:
    """Coerce a 0.0-1.0 rate, clamped and rounded for stable output."""
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(max(0.0, min(1.0, parsed)), 6)


def _json_safe(value: Any) -> Any:
    """Recursively coerce a JSON-like value for strict JSON serialization.

    Non-finite floats (``NaN``/``±Infinity``) are not valid JSON tokens and
    cannot be persisted by PostgreSQL jsonb; render them as ``null`` instead
    of emitting tokens that strict BI parsers reject.
    """
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_text(value: Any) -> str:
    """Render a nested value as compact, deterministic JSON text."""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(
                _json_safe(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return _safe_text(value)
    return _safe_text(value)


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with a formula starter (``=``, ``+``, ``-``, ``@``) or
    with a tab / carriage return / newline are prefixed with a single quote
    so Excel, LibreOffice, and Google Sheets treat them as literal text.
    Formula starters hidden behind leading whitespace are also caught,
    because spreadsheet parsers trim whitespace before evaluating a cell.
    """
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped[:1] in _FORMULA_STARTERS or value[:1] in _CONTROL_STARTERS:
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in ("generated_at", "user_id", "format_version", "project_id"):
        value = metadata.get(key)
        if value is None:
            continue
        rows.append((key, _safe_text(value)))
    return rows


def _summary_rows(data: dict[str, Any]) -> list[tuple[str, object]]:
    """Render the digest summary as deterministic key/value rows."""
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    keys = (
        _PORTFOLIO_SUMMARY_KEYS
        if "user_id" in data
        else _PROJECT_SUMMARY_KEYS
    )
    rows: list[tuple[str, object]] = []
    for key in keys:
        if key not in summary:
            continue
        value = summary.get(key)
        if key == "coverage_rate_pct":
            parsed = _safe_float(value)
            rows.append((key, "" if parsed is None else parsed))
        elif key == "oldest_unscored_age_days":
            rows.append((key, "" if value is None else _safe_int(value)))
        elif key == "narrative":
            rows.append((key, _safe_text(value)))
        else:
            rows.append((key, "" if value is None else value))
    if "learning_eligible_only" in data:
        rows.append(
            (
                "learning_eligible_only",
                "true" if data["learning_eligible_only"] else "false",
            )
        )
    return rows


def _is_portfolio(data: dict[str, Any]) -> bool:
    """Whether a payload carries per-project attribution on its items."""
    if "user_id" in data:
        return True
    return any(
        isinstance(row, dict) and "project_id" in row
        for row in data.get("items") or []
    )


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in data.get("items") or [] if isinstance(row, dict)
    ]


def _csv_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ""


def _item_headers(include_project_id: bool) -> list[str]:
    headers = list(_ITEM_HEADERS)
    if include_project_id:
        headers.insert(1, "project_id")
    return headers


def _item_values(
    row: dict[str, Any],
    include_project_id: bool,
) -> list[object]:
    """Render one unscored-simulation row as CSV-safe scalar values."""
    values: list[object] = [
        _safe_int(row.get("simulation_id")) or "",
        _safe_text(row.get("created_at")),
        _safe_int(row.get("age_days")),
        "" if row.get("signal_quality") is None
        else _bounded_rate(row.get("signal_quality")),
        "" if row.get("predicted_conversion_rate") is None
        else _bounded_rate(row.get("predicted_conversion_rate")),
        _safe_text(row.get("product_type_detected")),
        _safe_text(row.get("primary_failure_domain")),
        _csv_bool(row.get("has_results")),
        _csv_bool(row.get("learning_eligible")),
        _safe_text(row.get("urgency")),
        _safe_text(row.get("recommendation")),
    ]
    if include_project_id:
        values.insert(1, _safe_int(row.get("project_id")) or "")
    return values


def outcome_gaps_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-gaps digest payload as a multi-section CSV."""
    data = _as_dict(payload)
    include_project_id = _is_portfolio(data)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Outcome Feedback Gaps Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_rows(data):
        _write_row(writer, [key, value])
    _write_row(writer, [])

    _write_row(writer, ["section", "Unscored Simulations"])
    _write_row(writer, _item_headers(include_project_id))
    for row in _items(data):
        _write_row(writer, _item_values(row, include_project_id))

    return buffer.getvalue()


def outcome_gaps_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-gaps digest payload as a strict JSON document."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "outcome_gaps": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    parsed = _bounded_rate(value)
    if parsed is None:
        return "—"
    return f"{parsed:.2%}"


def _md_percent(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "—"
    return f"{parsed:.1f}%"


def _md_yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "—"


def _summary_label(key: str) -> str:
    labels = {
        "project_count": "Projects",
        "projects_with_gaps": "Projects with gaps",
        "total_completed": "Completed simulations",
        "scored": "Scored",
        "unscored": "Unscored",
        "coverage_rate_pct": "Coverage rate",
        "learning_eligible_unscored": "Learning-eligible unscored",
        "high_priority_unscored": "High-priority unscored",
        "oldest_unscored_age_days": "Oldest gap (days)",
        "learning_eligible_only": "Filter",
    }
    return labels.get(key, key)


def _summary_md_value(key: str, value: Any) -> str:
    if key == "coverage_rate_pct":
        return _md_percent(value)
    if key == "oldest_unscored_age_days":
        return "—" if value is None else _safe_text(value)
    if key == "learning_eligible_only":
        return "true" if value else "false"
    return _escape_md_cell(value)


def outcome_gaps_to_markdown(
    payload: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-gaps digest payload as a founder-facing brief."""
    data = _as_dict(payload)
    include_project_id = _is_portfolio(data)
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    keys = (
        _PORTFOLIO_SUMMARY_KEYS
        if "user_id" in data
        else _PROJECT_SUMMARY_KEYS
    )

    lines: list[str] = []
    lines.append("# Outcome Feedback Gaps")
    lines.append("")
    lines.append(
        "Completed simulation runs that still need a real-world outcome "
        "recorded against them, oldest first."
    )
    lines.append("")
    if metadata:
        generated = _safe_text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for key in keys:
        if key not in summary:
            continue
        lines.append(
            f"| {_escape_md_cell(_summary_label(key))} | "
            f"{_summary_md_value(key, summary.get(key))} |"
        )
    if "learning_eligible_only" in data:
        lines.append(
            "| Filter | "
            f"{'learning-eligible only' if data['learning_eligible_only'] else 'all unscored'} |"
        )
    lines.append("")

    narrative = _safe_text(summary.get("narrative"))
    if narrative:
        lines.append(_escape_md_cell(narrative))
        lines.append("")

    rows = _items(data)
    lines.append("## Unscored Simulations")
    lines.append("")
    project_column = "| Project " if include_project_id else ""
    project_align = "| ---: " if include_project_id else ""
    lines.append(
        f"| Simulation {project_column}| Created | Age (days) | Signal | "
        "Predicted | Product | Failure domain | Learning-eligible | "
        "Urgency | Recommendation |"
    )
    lines.append(
        f"| ---: {project_align}| --- | ---: | ---: | ---: | --- | --- | "
        "--- | --- | --- |"
    )
    for row in rows:
        project_cells = (
            f"| {_safe_int(row.get('project_id')) or '—'} "
            if include_project_id
            else ""
        )
        lines.append(
            "| {sim} {project}| {created} | {age} | {signal} | {predicted} | "
            "{product} | {domain} | {eligible} | {urgency} | {recommendation} |".format(
                sim=_safe_int(row.get("simulation_id")) or "—",
                project=project_cells,
                created=_escape_md_cell(row.get("created_at")) or "—",
                age=_safe_int(row.get("age_days")),
                signal=_md_pct(row.get("signal_quality")),
                predicted=_md_pct(row.get("predicted_conversion_rate")),
                product=_escape_md_cell(row.get("product_type_detected"))
                or "—",
                domain=_escape_md_cell(row.get("primary_failure_domain"))
                or "—",
                eligible=_md_yes_no(row.get("learning_eligible")),
                urgency=_escape_md_cell(row.get("urgency")) or "—",
                recommendation=_escape_md_cell(row.get("recommendation"))
                or "—",
            )
        )
    lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Outcome feedback gaps"]
    user_id = _safe_int(data.get("user_id"))
    project_id = _safe_int(data.get("project_id"))
    if user_id:
        footer.append(f"User {user_id}")
    elif project_id:
        footer.append(f"Project {project_id}")
    if data.get("generated_at"):
        footer.append(
            f"Generated {_escape_md_cell(data.get('generated_at'))}"
        )
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "outcome_gaps_to_csv",
    "outcome_gaps_to_json",
    "outcome_gaps_to_markdown",
]
