"""CSV, JSON, and Markdown exports for the portfolio validation-momentum
payload.

``GET /users/me/validation-momentum`` ranks every owned project by
validation progress and forecasts parallel de-risking pace.  These exports
put that portfolio answer into a founder's spreadsheet, data pipeline, or
weekly report.  Formatting is pure and reuses the exact response payload
produced by the JSON endpoint.

CSV is a multi-section document: metadata header, cross-project summary,
insights, caveats, and one row per ranked project.  Cells are guarded
against spreadsheet formula injection.  JSON is an envelope with stable
metadata and the unmodified payload.  Markdown is a founder-facing brief
with a summary table, focus callout, insight/caveat bullets, and a compact
projects table.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "project_count",
    "projects_with_evidence",
    "projects_without_evidence",
    "projects_needing_attention",
    "projects_complete",
    "total_assumptions",
    "total_evidence_rows",
    "assumptions_with_evidence",
    "de_risked_count",
    "challenged_count",
    "pending_count",
    "evidence_coverage_pct",
    "validation_score",
    "coverage_velocity_per_week",
    "de_risk_velocity_per_week",
    "target_de_risked_pct",
    "remaining_for_coverage",
    "remaining_for_target",
    "weeks_to_full_coverage",
    "weeks_to_de_risked_target",
    "portfolio_trend",
)

_PROJECT_HEADERS: tuple[str, ...] = (
    "rank",
    "project_id",
    "project_title",
    "status",
    "trend",
    "total_assumptions",
    "de_risked_count",
    "challenged_count",
    "pending_count",
    "evidence_coverage_pct",
    "validation_score",
    "remaining_for_target",
    "weeks_to_de_risked_target",
    "confident",
    "focus_reason",
)

_LABELS: dict[str, str] = {
    "project_count": "Projects",
    "projects_with_evidence": "With evidence",
    "projects_without_evidence": "Without evidence",
    "projects_needing_attention": "Needing attention",
    "projects_complete": "Complete",
    "total_assumptions": "Total assumptions",
    "total_evidence_rows": "Evidence rows",
    "assumptions_with_evidence": "Assumptions with evidence",
    "de_risked_count": "De-risked",
    "challenged_count": "Challenged",
    "pending_count": "Pending",
    "evidence_coverage_pct": "Coverage",
    "validation_score": "Validation score",
    "coverage_velocity_per_week": "Coverage velocity (/week)",
    "de_risk_velocity_per_week": "De-risking velocity (/week)",
    "target_de_risked_pct": "De-risk target share",
    "remaining_for_coverage": "Remaining for full coverage",
    "remaining_for_target": "Remaining for target",
    "weeks_to_full_coverage": "Weeks to full coverage",
    "weeks_to_de_risked_target": "Weeks to target",
    "portfolio_trend": "Portfolio cadence",
}

# Fraction metrics read best as percentages in the Markdown brief.
_PCT_KEYS: frozenset[str] = frozenset(
    {
        "evidence_coverage_pct",
        "validation_score",
        "target_de_risked_pct",
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
            "format_version",
        )
    ]


def portfolio_validation_momentum_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a portfolio-momentum payload as a multi-section CSV."""
    data = _as_dict(payload)
    summary = _as_dict(data.get("summary"))
    insights = summary.get("insights") or []
    caveats = summary.get("caveats") or []
    projects = data.get("projects") or []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Portfolio Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        value = summary.get(key)
        _write_row(
            writer,
            [key, _text(value) if value is not None else ""],
        )
    _write_row(writer, [])

    if insights:
        _write_row(writer, ["section", "Portfolio Insights"])
        for text in insights:
            _write_row(writer, [text])
        _write_row(writer, [])

    if caveats:
        _write_row(writer, ["section", "Portfolio Caveats"])
        for text in caveats:
            _write_row(writer, [text])
        _write_row(writer, [])

    if projects:
        _write_row(writer, ["section", "Projects"])
        _write_row(writer, list(_PROJECT_HEADERS))
        for project in projects:
            project_data = _as_dict(project)
            _write_row(
                writer,
                [
                    _text(project_data.get(key))
                    if project_data.get(key) is not None
                    else ""
                    for key in _PROJECT_HEADERS
                ],
            )
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Portfolio Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def portfolio_validation_momentum_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a portfolio-momentum payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "portfolio_validation_momentum": _json_safe(_as_dict(payload)),
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
    """Generic Markdown cell renderer; empty values render as a dash."""
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def _md_pct(value: Any) -> str:
    """Format a 0–1 fraction as a percentage, or a dash when absent."""
    if value is None or value == "":
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{fraction * 100:.1f}%"


def portfolio_validation_momentum_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a portfolio-momentum payload as a founder-facing brief."""
    data = _as_dict(payload)
    summary = _as_dict(data.get("summary"))
    insights = summary.get("insights") or []
    caveats = summary.get("caveats") or []
    projects = data.get("projects") or []

    lines: list[str] = []
    lines.append("# Portfolio Validation Momentum")
    lines.append("")
    lines.append(
        "How fast your whole portfolio is being validated — ranked projects "
        "and the parallel de-risking forecast."
    )
    lines.append("")

    if metadata:
        generated = _text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    focus_title = summary.get("focus_project_title")
    focus_reason = summary.get("focus_reason")
    if focus_title:
        focus_line = f"**Next focus: {_escape_md_cell(focus_title)}**"
        if focus_reason:
            focus_line += f" — {_escape_md_cell(focus_reason)}"
        lines.append(focus_line)
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for key in _SUMMARY_KEYS:
        value = summary.get(key)
        rendered = _md_pct(value) if key in _PCT_KEYS else _md_cell(value)
        lines.append(
            f"| {_escape_md_cell(_LABELS.get(key, key))} | {rendered} |"
        )
    lines.append("")

    if insights:
        lines.append("## Insights")
        lines.append("")
        for text in insights:
            lines.append(f"- {_escape_md_cell(text)}")
        lines.append("")

    if caveats:
        lines.append("### Caveats")
        lines.append("")
        for text in caveats:
            lines.append(f"- {_escape_md_cell(text)}")
        lines.append("")

    if projects:
        lines.append("## Projects")
        lines.append("")
        lines.append(
            "| Rank | Project | Status | De-risked | Pending | "
            "Coverage | Weeks to target |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for project in projects:
            project_data = _as_dict(project)
            lines.append(
                "| {rank} | {title} | {status} | {derisked} | {pending} | "
                "{coverage} | {weeks} |".format(
                    rank=_md_cell(project_data.get("rank")),
                    title=_escape_md_cell(
                        str(project_data.get("project_title") or "")
                    )
                    or "—",
                    status=_md_cell(project_data.get("status")),
                    derisked=_md_cell(project_data.get("de_risked_count")),
                    pending=_md_cell(project_data.get("pending_count")),
                    coverage=_md_pct(
                        project_data.get("evidence_coverage_pct")
                    ),
                    weeks=_md_cell(
                        project_data.get("weeks_to_de_risked_target")
                    ),
                )
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Portfolio validation momentum"]
    user_id = (
        _text(metadata.get("user_id"))
        if metadata
        else _text(data.get("user_id"))
    )
    if user_id:
        footer.append(f"User {user_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(
            f"Generated {_escape_md_cell(_text(metadata['generated_at']))}"
        )
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "portfolio_validation_momentum_to_csv",
    "portfolio_validation_momentum_to_json",
    "portfolio_validation_momentum_to_markdown",
]
