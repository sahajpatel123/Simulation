"""CSV, JSON, and Markdown exports for the recovery-plan payload.

The recovery endpoint answers *how to get killed assumptions back on
track*; these exports put the same answer in a founder's spreadsheet,
data pipeline, or weekly validation report. Formatting is pure and
reuses the exact response payload produced by
``GET /projects/{id}/assumption-recovery-plan``.

CSV is a multi-section document: metadata header, project-level recovery
summary (counts plus theme breakdown), the flattened play list (one row
per recovery action), the narrative, and the planner meta. Numeric
columns stay native for spreadsheets; free-form text cells are guarded
against formula injection. JSON is an envelope with stable metadata and
the unmodified payload. Markdown is a founder-facing brief with a
summary table and one line per play.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "total_assumptions",
    "attention_count",
    "killed_count",
    "inconsistent_count",
)

_SUMMARY_LABELS: dict[str, str] = {
    "total_assumptions": "Total assumptions",
    "attention_count": "Assumptions needing recovery",
    "killed_count": "Killed",
    "inconsistent_count": "Inconsistent",
}

_ACTION_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "category",
    "trigger",
    "theme",
    "action_order",
    "title",
    "method_label",
    "cost_tier",
    "estimated_duration_days",
    "success_threshold",
)

_NUMERIC_KEYS: frozenset[str] = frozenset(
    {
        "assumption_id",
        "action_order",
        "estimated_duration_days",
    }
)


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain mapping into a plain dictionary."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _text(value: Any) -> str:
    """Render a scalar for export without leaking Python ``None`` text."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formulas while preserving ordinary values."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped[:1] in ("=", "+", "-", "@") or value[:1] in (
        "\t",
        "\r",
        "\n",
    ):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write one CSV row with the formula guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _cell(item: dict[str, Any], key: str) -> object:
    """Native number when the column is numeric and the value is one."""
    value = item.get(key, "")
    if key in _NUMERIC_KEYS:
        if isinstance(value, bool):
            return _text(value)
        if isinstance(value, (int, float)):
            return value
        if value is None:
            return ""
    return _text(value)


def _json_safe(value: Any) -> Any:
    """Replace non-finite numbers before strict JSON serialisation."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Return stable metadata rows for the top of the CSV document."""
    if not metadata:
        return []
    return [
        (key, _text(metadata.get(key)))
        for key in (
            "generated_at",
            "user_id",
            "project_id",
            "format_version",
        )
    ]


def _flatten_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One flat record per recovery action, carrying its parent context."""
    flat: list[dict[str, Any]] = []
    for raw_row in data.get("rows") or []:
        row_item = _as_dict(raw_row)
        if not row_item:
            continue
        for action in row_item.get("actions") or []:
            act = _as_dict(action)
            if not act:
                continue
            flat.append(
                {
                    "assumption_id": row_item.get("assumption_id"),
                    "assumption_text": row_item.get("assumption_text", ""),
                    "category": row_item.get("category"),
                    "trigger": row_item.get("trigger", ""),
                    "theme": row_item.get("theme", ""),
                    "action_order": act.get("order"),
                    "title": act.get("title", ""),
                    "method_label": act.get("method_label", ""),
                    "cost_tier": act.get("cost_tier", ""),
                    "estimated_duration_days": act.get(
                        "estimated_duration_days"
                    ),
                    "success_threshold": act.get("success_threshold", ""),
                }
            )
    return flat


def recovery_plan_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a recovery-plan payload as a multi-section CSV."""
    data = _as_dict(payload)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Recovery Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _write_row(writer, [key, value])
        else:
            _write_row(
                writer, [key, _text(value) if value is not None else ""]
            )
    for theme, count in sorted((_as_dict(data.get("theme_counts"))).items()):
        _write_row(writer, [f"theme:{theme}", count])
    _write_row(writer, [])

    _write_row(writer, ["section", "Recovery Plays"])
    _write_row(writer, list(_ACTION_HEADERS))
    for record in _flatten_actions(data):
        _write_row(writer, [_cell(record, key) for key in _ACTION_HEADERS])
    _write_row(writer, [])

    narrative = data.get("narrative")
    if narrative:
        _write_row(writer, ["section", "Next Steps"])
        _write_row(writer, [narrative])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Recovery Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def recovery_plan_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a recovery-plan payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "recovery_plan": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    """Escape pipe characters so cells can't break Markdown tables."""
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def recovery_plan_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a recovery-plan payload as a founder-facing brief."""
    data = _as_dict(payload)
    rows = data.get("rows") or []

    lines: list[str] = []
    lines.append("# Assumption Recovery Plan")
    lines.append("")
    lines.append(
        "Ordered plays for every killed or self-contradictory assumption — "
        "a reframed hypothesis plus the concrete re-test to run."
    )
    lines.append("")

    if metadata:
        generated = _text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for key in _SUMMARY_KEYS:
        lines.append(
            f"| {_escape_md_cell(_SUMMARY_LABELS.get(key, key))} "
            f"| {_md_cell(data.get(key))} |"
        )
    themes = _as_dict(data.get("theme_counts"))
    for theme, count in sorted(themes.items()):
        lines.append(f"| {_escape_md_cell(str(theme)).title()} claims | {count} |")
    lines.append("")

    if rows:
        lines.append("## Recovery Plays")
        lines.append("")
        lines.append(
            "| # | Assumption | Trigger | Theme | Play | Method "
            "| Cost | Days | Success bar |"
        )
        lines.append("| ---: | --- | --- | --- | --- | --- | --- | ---: | --- |")
        for raw_row in rows:
            item = _as_dict(raw_row)
            if not item:
                continue
            for action in item.get("actions") or []:
                act = _as_dict(action)
                if not act:
                    continue
                lines.append(
                    f"| {act.get('order', '')} "
                    f"| {_escape_md_cell(item.get('assumption_text', ''))} "
                    f"| {_escape_md_cell(item.get('trigger', ''))} "
                    f"| {_escape_md_cell(item.get('theme', ''))} "
                    f"| {_escape_md_cell(act.get('title', ''))} "
                    f"| {_escape_md_cell(act.get('method_label', ''))} "
                    f"| {_escape_md_cell(str(act.get('cost_tier', '')).lower())} "
                    f"| {act.get('estimated_duration_days', '—')} "
                    f"| {_escape_md_cell(act.get('success_threshold') or '—')} |"
                )
        lines.append("")

    narrative = data.get("narrative")
    if narrative:
        lines.append("## Next Steps")
        lines.append("")
        lines.append(f"**{_escape_md_cell(narrative)}**")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Recovery plan"]
    project_id = _text(metadata.get("project_id")) if metadata else ""
    if not project_id:
        project_id = _text(data.get("project_id"))
    if project_id:
        footer.append(f"Project {project_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(
            f"Generated {_escape_md_cell(_text(metadata['generated_at']))}"
        )
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "recovery_plan_to_csv",
    "recovery_plan_to_json",
    "recovery_plan_to_markdown",
]
