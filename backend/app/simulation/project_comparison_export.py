"""CSV / JSON / Markdown export helpers for the project-comparison read.

The project-comparison endpoint (``POST /api/v1/projects/compare``) returns a
side-by-side snapshot of two owned projects across health, funnel, assumptions,
outcomes, and risk signals. This module renders the same deterministic payload
for download:

* CSV — a multi-section spreadsheet (summary, key signals, project refs, and
  the dimension comparison table) so founders can keep a record in Sheets or
  Excel.
* JSON — a machine-readable envelope for tools and integrations.
* Markdown — a concise founder-facing brief for docs, Notion, or an investor
  update.

The module stays pure and defensive: missing fields, malformed rows, and empty
sections degrade to safe defaults without raising.
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    A cell is neutralised when it begins with a formula character or when it
    embeds ``=`` inside a prefix such as ``A:=HYPERLINK(...)`` so the whole
    cell can never be interpreted as an executable formula by Excel.
    """
    if isinstance(value, str):
        if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
        if "=" in value:
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "project_id",
        "comparison_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _summary_dict(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("summary")
    if isinstance(summary, dict):
        return summary
    return {}


def _projects(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in _as_list(data.get("projects")) if isinstance(row, dict)
    ]


def _dimensions(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in _as_list(data.get("dimensions")) if isinstance(row, dict)
    ]


def _key_signals(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_list(_summary_dict(data).get("key_signals"))
        if isinstance(row, dict)
    ]


def _csv_scalar(value: Any) -> object:
    """Render a nested value as a CSV-safe scalar."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def project_comparison_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project-comparison payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Project Comparison Summary"])
    _write_row(writer, ["key", "value"])
    summary = _summary_dict(data)
    for key in (
        "winner_project_id",
        "winner_label",
        "verdict",
        "narrative",
    ):
        _write_row(writer, [key, _csv_scalar(summary.get(key))])
    _write_row(writer, ["comparison_id", _safe_text(data.get("comparison_id"))])
    _write_row(writer, ["generated_at", _safe_text(data.get("generated_at"))])
    _write_row(writer, [])

    # Key signals.
    signals = _key_signals(data)
    _write_row(writer, ["section", "Key Signals"])
    _write_row(writer, ["label", "value", "severity", "display"])
    for signal in signals:
        _write_row(
            writer,
            [
                _csv_scalar(signal.get("label")),
                _csv_scalar(signal.get("value")),
                _csv_scalar(signal.get("severity")),
                _csv_scalar(signal.get("display")),
            ],
        )
    _write_row(writer, [])

    # Project references.
    _write_row(writer, ["section", "Projects Compared"])
    _write_row(
        writer,
        [
            "project_id",
            "title",
            "status",
            "health_score",
            "health_verdict",
            "simulation_count",
            "latest_conversion_rate",
            "latest_confidence_score",
            "assumption_count",
            "outcome_count",
            "pending_decision_count",
            "critical_finding_count",
            "weak_link_count",
            "brief_completed",
            "primary_failure_domain",
            "product_type_detected",
        ],
    )
    for project in _projects(data):
        _write_row(
            writer,
            [
                _safe_int(project.get("project_id")),
                _csv_scalar(project.get("title")),
                _csv_scalar(project.get("status")),
                _safe_int(project.get("health_score")),
                _csv_scalar(project.get("health_verdict")),
                _safe_int(project.get("simulation_count")),
                _safe_float(project.get("latest_conversion_rate")),
                _safe_float(project.get("latest_confidence_score")),
                _safe_int(project.get("assumption_count")),
                _safe_int(project.get("outcome_count")),
                _safe_int(project.get("pending_decision_count")),
                _safe_int(project.get("critical_finding_count")),
                _safe_int(project.get("weak_link_count")),
                "yes" if project.get("brief_completed") else "no",
                _csv_scalar(project.get("primary_failure_domain")),
                _csv_scalar(project.get("product_type_detected")),
            ],
        )
    _write_row(writer, [])

    # Dimension comparison.
    _write_row(writer, ["section", "Dimension Comparison"])
    _write_row(
        writer,
        [
            "dimension",
            "label",
            "higher_is_better",
            "winner",
            "project_a",
            "project_b",
            "display_a",
            "display_b",
        ],
    )
    for dimension in _dimensions(data):
        _write_row(
            writer,
            [
                _csv_scalar(dimension.get("dimension")),
                _csv_scalar(dimension.get("label")),
                "yes" if dimension.get("higher_is_better") else "no",
                _csv_scalar(dimension.get("winner")),
                _csv_scalar(dimension.get("a")),
                _csv_scalar(dimension.get("b")),
                _csv_scalar(dimension.get("display_a")),
                _csv_scalar(dimension.get("display_b")),
            ],
        )
    _write_row(writer, [])

    return buffer.getvalue()


def project_comparison_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project-comparison payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "project_comparison": _as_dict(payload),
        },
        default=str,
        indent=2,
    )


def _escape_md_cell(value: Any) -> str:
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    parsed = _safe_float(value)
    return f"{max(0.0, min(1.0, parsed)):.2%}"


def project_comparison_to_markdown(
    payload: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project-comparison payload as a founder-facing brief."""
    data = _as_dict(payload)
    summary = _summary_dict(data)

    lines: list[str] = []
    lines.append("# Project Comparison")
    lines.append("")
    lines.append(
        "Side-by-side comparison of two dossiers: headline verdict, "
        "project snapshots, and the dimension table behind the winner."
    )
    lines.append("")
    if metadata:
        generated = _safe_text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Verdict")
    lines.append("")
    winner_id = summary.get("winner_project_id")
    winner_line = _escape_md_cell(summary.get("winner_label"))
    if winner_id is not None:
        winner_line += f" (project {_safe_int(winner_id)})"
    lines.append(
        f"**{_escape_md_cell(summary.get('verdict'))}** — winner "
        f"{winner_line}."
    )
    narrative = _safe_text(summary.get("narrative"))
    if narrative:
        lines.append("")
        lines.append(narrative)
    lines.append("")

    lines.append("## Projects Compared")
    lines.append("")
    lines.append(
        "| Label | Project | Status | Health | Conversion | Confidence | Brief | Type |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | --- | --- |")
    for idx, project in enumerate(_projects(data), start=1):
        label = chr(ord("A") + idx - 1) if idx <= 26 else f"Project {idx}"
        lines.append(
            "| {label} | {title} | {status} | {health} | {conversion} | "
            "{confidence} | {brief} | {ptype} |".format(
                label=label,
                title=_escape_md_cell(project.get("title")) or "—",
                status=_escape_md_cell(project.get("status")) or "—",
                health=_safe_int(project.get("health_score")),
                conversion=_md_pct(project.get("latest_conversion_rate")),
                confidence=_md_pct(project.get("latest_confidence_score")),
                brief="yes" if project.get("brief_completed") else "no",
                ptype=_escape_md_cell(project.get("product_type_detected"))
                or "—",
            )
        )
    lines.append("")

    lines.append("## Dimension Comparison")
    lines.append("")
    dimensions = _dimensions(data)
    if not dimensions:
        lines.append("No dimension comparison is available.")
    else:
        lines.append(
            "| Dimension | Metric | Project A | Project B | Winner |"
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for dimension in dimensions:
            lines.append(
                "| {key} | {label} | {a} | {b} | {winner} |".format(
                    key=_escape_md_cell(dimension.get("dimension")),
                    label=_escape_md_cell(dimension.get("label")) or "—",
                    a=_escape_md_cell(dimension.get("display_a")) or "—",
                    b=_escape_md_cell(dimension.get("display_b")) or "—",
                    winner=_escape_md_cell(dimension.get("winner")) or "—",
                )
            )
    lines.append("")

    signals = _key_signals(data)
    if signals:
        lines.append("## Key Signals")
        lines.append("")
        for signal in signals:
            display = _safe_text(signal.get("display"))
            if not display:
                display = _safe_text(signal.get("label"))
            lines.append(
                f"- **{_escape_md_cell(signal.get('label'))}** — "
                f"{_escape_md_cell(display)}"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = []
    if data.get("comparison_id"):
        footer.append(f"Comparison {_escape_md_cell(data.get('comparison_id'))}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "project_comparison_to_csv",
    "project_comparison_to_json",
    "project_comparison_to_markdown",
]
