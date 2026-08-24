"""CSV, JSON, and Markdown exports for the evidence-quality payload.

The evidence-quality endpoint answers *how much each logged experiment
deserves to be trusted*; these exports put the same grading in a
founder's spreadsheet, data pipeline, or weekly validation report.
Formatting is pure and reuses the exact response payload produced by
``GET /projects/{id}/evidence-quality``.

CSV is a multi-section document: metadata header, project-level quality
summary (including the evidence-quality index), the full lowest-first
assumption quality table, the weakest link, the narrative, and the
scoring configuration. Cells are guarded against spreadsheet formula
injection so free-form assumption text stays inert when opened in a
spreadsheet. JSON is an envelope with stable metadata and the unmodified
payload. Markdown is a founder-facing brief with summary, weakest-link
callout, and per-assumption quality tables.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.export_utils import write_row

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "total_assumptions",
    "tested_count",
    "untested_count",
    "high_count",
    "medium_count",
    "low_count",
    "evidence_quality_index",
    "index_label",
)

_SUMMARY_LABELS: dict[str, str] = {
    "total_assumptions": "Total assumptions",
    "tested_count": "Tested",
    "untested_count": "Untested",
    "high_count": "High quality",
    "medium_count": "Medium quality",
    "low_count": "Low quality",
    "evidence_quality_index": "Evidence quality index",
    "index_label": "Index label",
}

_ROW_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "category",
    "evidence_count",
    "latest_result",
    "latest_method",
    "latest_method_reliability",
    "latest_age_days",
    "quality",
    "quality_label",
    "reasons",
)

# Columns whose values stay native numbers in the CSV (so spreadsheets can
# compute on them); only strings ever need the formula guard.
_NUMERIC_KEYS: frozenset[str] = frozenset(
    {
        "assumption_id",
        "evidence_count",
        "latest_method_reliability",
        "latest_age_days",
        "quality",
    }
)

_WEAK_LINK_KEYS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "quality",
    "quality_label",
    "reason",
)

_WEAK_LINK_LABELS: dict[str, str] = {
    "assumption_id": "Assumption ID",
    "assumption_text": "Assumption",
    "quality": "Quality",
    "quality_label": "Label",
    "reason": "Why",
}


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
    write_row(writer, [_safe_csv_cell(value) for value in row])


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


def _meta_rows(meta: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Flatten the scoring meta into sorted (key, text) CSV rows.

    Nested mappings (e.g. the per-method reliability table) become
    dotted keys so every value stays a single scalar cell.
    """
    rows: list[tuple[str, str]] = []
    for key in sorted(meta):
        value = meta[key]
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            rows.extend(_meta_rows(value, prefix=f"{name}."))
        elif isinstance(value, (list, tuple)):
            rows.append((name, "; ".join(_text(item) for item in value)))
        else:
            rows.append((name, _text(value)))
    return rows


def evidence_quality_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-quality payload as a multi-section CSV."""
    data = _as_dict(payload)
    rows = data.get("rows") or []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Quality Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _write_row(writer, [key, value])
        else:
            _write_row(writer, [key, _text(value) if value is not None else ""])
    _write_row(writer, [])

    _write_row(writer, ["section", "Assumption Quality"])
    _write_row(writer, list(_ROW_HEADERS))
    for raw_row in rows:
        item = _as_dict(raw_row)
        if not item:
            continue
        rendered = {key: item.get(key) for key in _ROW_HEADERS}
        rendered["reasons"] = "; ".join(_text(reason) for reason in (item.get("reasons") or []))
        _write_row(
            writer,
            [_cell(rendered, key) for key in _ROW_HEADERS],
        )
    _write_row(writer, [])

    weakest = data.get("weakest_link")
    if weakest:
        item = _as_dict(weakest)
        _write_row(writer, ["section", "Weakest Link"])
        _write_row(writer, ["key", "value"])
        for key in _WEAK_LINK_KEYS:
            _write_row(
                writer,
                [
                    _WEAK_LINK_LABELS.get(key, key),
                    _cell(item, key),
                ],
            )
        _write_row(writer, [])

    narrative = data.get("narrative")
    if narrative:
        _write_row(writer, ["section", "Narrative"])
        _write_row(writer, [narrative])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Quality Meta"])
        _write_row(writer, ["key", "value"])
        for key, value in _meta_rows(meta):
            _write_row(writer, [key, value])
        _write_row(writer, [])

    return buffer.getvalue()


def evidence_quality_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-quality payload as a strict JSON envelope."""
    return (
        json.dumps(
            {
                "metadata": _json_safe(metadata or {}),
                "evidence_quality": _json_safe(_as_dict(payload)),
            },
            default=str,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def _escape_md_cell(value: Any) -> str:
    """Escape pipe characters so cells can't break Markdown tables."""
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    """Format a 0–1 float as a percentage, or return a dash."""
    if value is None:
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{fraction * 100:.1f}%"


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def evidence_quality_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-quality payload as a founder-facing brief."""
    data = _as_dict(payload)
    rows = data.get("rows") or []

    lines: list[str] = []
    lines.append("# Evidence Quality")
    lines.append("")
    lines.append(
        "How much each logged experiment deserves to be trusted — graded "
        "on method reliability, decisiveness, metric presence, and "
        "recency."
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
            f"| {_escape_md_cell(_SUMMARY_LABELS.get(key, key))} | {_md_cell(data.get(key))} |"
        )
    lines.append("")

    weakest = data.get("weakest_link")
    if weakest:
        item = _as_dict(weakest)
        lines.append("## Weakest Link")
        lines.append("")
        lines.append(
            f"**“{_escape_md_cell(item.get('assumption_text', ''))}”** "
            f"— quality {_md_pct(item.get('quality'))} "
            f"({_escape_md_cell(item.get('quality_label', ''))})"
        )
        lines.append("")
        reason = item.get("reason")
        if reason:
            lines.append(f"{_escape_md_cell(reason)}")
            lines.append("")

    if rows:
        lines.append("## Assumption Quality")
        lines.append("")
        lines.append(
            "| # | Assumption | Category | Evidence | Latest | Method "
            "| Reliability | Age (d) | Quality | Label |"
        )
        lines.append("| ---: | --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- |")
        for idx, raw_row in enumerate(rows, start=1):
            item = _as_dict(raw_row)
            if not item:
                continue
            lines.append(
                f"| {idx} "
                f"| {_escape_md_cell(item.get('assumption_text', ''))} "
                f"| {_escape_md_cell(item.get('category', ''))} "
                f"| {_md_cell(item.get('evidence_count', 0))} "
                f"| {_escape_md_cell(item.get('latest_result') or '—')} "
                f"| {_escape_md_cell(item.get('latest_method') or '—')} "
                f"| {_md_pct(item.get('latest_method_reliability'))} "
                f"| {_md_cell(item.get('latest_age_days'))} "
                f"| {_md_pct(item.get('quality'))} "
                f"| {_escape_md_cell(item.get('quality_label', ''))} |"
            )
        lines.append("")

    narrative = data.get("narrative")
    if narrative:
        lines.append(f"**{_escape_md_cell(narrative)}**")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Evidence quality"]
    project_id = _text(metadata.get("project_id")) if metadata else ""
    if not project_id:
        project_id = _text(data.get("project_id"))
    if project_id:
        footer.append(f"Project {project_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(f"Generated {_escape_md_cell(_text(metadata['generated_at']))}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "evidence_quality_to_csv",
    "evidence_quality_to_json",
    "evidence_quality_to_markdown",
]
