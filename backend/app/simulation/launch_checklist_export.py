"""CSV / JSON / Markdown export helpers for the launch-checklist read.

The launch-checklist endpoint
(``GET /api/v1/simulations/{id}/launch-checklist``) returns a structured
readiness digest. This module renders that same payload for download:

* CSV — a multi-section spreadsheet (summary, checklist items,
  recommendations, meta) so founders can keep a record in Sheets/Excel.
* JSON — a machine-readable envelope for tools and integrations.
* Markdown — a concise founder-facing brief for docs, Notion, or an
  investor update.

The module stays pure and defensive: missing fields, malformed rows, and
unsupported severities degrade to safe defaults without raising.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.export_utils import write_row


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
    return str(value)


def _safe_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with formula-injection guard applied to every cell."""
    write_row(writer, [_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "simulation_id",
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _summary_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Extract the flat top-level fields used in the summary section."""
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "product_type": data.get("product_type"),
        "verdict": data.get("verdict"),
        "readiness_score": data.get("readiness_score"),
        "signal_quality": data.get("signal_quality"),
        "visible_assumptions": data.get("visible_assumptions"),
        "total_items": summary.get("total_items"),
        "evaluated_items": summary.get("evaluated_items"),
        "passed_items": summary.get("passed_items"),
        "warned_items": summary.get("warned_items"),
        "failed_items": summary.get("failed_items"),
        "skipped_items": summary.get("skipped_items"),
    }


def launch_checklist_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a launch-checklist payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Launch Readiness Summary"])
    _write_row(writer, ["key", "value"])
    summary_values = _summary_dict(data)
    for key, value in summary_values.items():
        _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, [])

    # Checklist items.
    _write_row(writer, ["section", "Checklist Items"])
    _write_row(
        writer,
        [
            "id",
            "category",
            "label",
            "status",
            "weight",
            "score",
            "detail",
        ],
    )
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("id")),
                _safe_text(item.get("category")),
                _safe_text(item.get("label")),
                _safe_text(item.get("status")),
                _safe_float(item.get("weight")),
                _safe_float(item.get("score")),
                _safe_text(item.get("detail")),
            ],
        )
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(writer, ["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            _write_row(writer, [recommendation])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    # Meta section.
    _write_row(writer, ["section", "Meta"])
    _write_row(writer, ["key", "value"])
    meta = data.get("meta") or {}
    if isinstance(meta, dict):
        for key in sorted(meta.keys()):
            value = meta[key]
            if isinstance(value, dict):
                _write_row(writer, [key, json.dumps(value, default=str)])
            else:
                _write_row(writer, [key, _safe_text(value)])

    return buffer.getvalue()


def launch_checklist_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a launch-checklist payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "launch_checklist": _as_dict(payload),
        },
        default=str,
        indent=2,
    )


def _escape_md_cell(value: Any) -> str:
    """Escape pipe and newline characters for a Markdown table cell."""
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _severity_label(status: str) -> str:
    """Humanise the checklist status label for Markdown."""
    value = _safe_text(status).strip().upper()
    if value == "PASS":
        return "PASS"
    if value == "WARN":
        return "WARN"
    if value == "FAIL":
        return "FAIL"
    if value == "SKIP":
        return "SKIP"
    return "INFO"


def launch_checklist_to_markdown(
    payload: Any,
    *,
    simulation_id: int | None = None,
    project_id: int | None = None,
    project_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a launch-checklist payload as a founder-facing Markdown brief."""
    data = _as_dict(payload)
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    title = (project_name or "TheCee").strip() or "TheCee"
    lines: list[str] = []
    lines.append(f"# {_escape_md_cell(title)} — Launch Readiness Checklist")
    lines.append("")
    lines.append(
        "This deterministic checklist scores the persisted simulation "
        "payload on results integrity, cluster coverage, signal quality, "
        "funnel sanity and assumption coverage."
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
    lines.append("| --- | ---: |")
    lines.append(f"| Verdict | {_escape_md_cell(data.get('verdict'))} |")
    lines.append(f"| Readiness score | {_safe_float(data.get('readiness_score')):.2f} |")
    if data.get("signal_quality") is not None:
        lines.append(f"| Signal quality | {_safe_float(data.get('signal_quality')):.2f} |")
    if data.get("visible_assumptions") is not None:
        lines.append(f"| Visible assumptions | {_safe_text(data.get('visible_assumptions'))} |")
    if data.get("product_type"):
        lines.append(f"| Product type | {_escape_md_cell(data.get('product_type'))} |")
    lines.append(f"| Total items | {summary.get('total_items', 0)} |")
    lines.append(
        "| Passed / Warned / Failed | "
        f"{summary.get('passed_items', 0)} / "
        f"{summary.get('warned_items', 0)} / "
        f"{summary.get('failed_items', 0)} |"
    )
    if "coverage" in meta:
        coverage = _safe_float(meta.get("coverage"))
        lines.append(f"| Cluster coverage | {coverage:.0%} |")
    if "expected_clusters" in meta:
        lines.append(f"| Expected clusters | {_safe_text(meta.get('expected_clusters'))} |")
    lines.append("")

    lines.append("## Checklist")
    lines.append("")
    items = data.get("items") or []
    if not items:
        lines.append("No checklist items available.")
    else:
        lines.append("| Status | ID | Check | Category | Weight | Score | Detail |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | --- |")
        for item in items:
            if not isinstance(item, dict):
                continue
            status = _severity_label(item.get("status"))
            item_id = _escape_md_cell(item.get("id"))
            label = _escape_md_cell(item.get("label"))
            category = _escape_md_cell(item.get("category"))
            weight = _safe_float(item.get("weight"))
            score = _safe_float(item.get("score"))
            detail = _escape_md_cell(item.get("detail"))
            lines.append(
                f"| {status} | {item_id} | {label} | {category} | {weight:.2f} | "
                f"{score:.2f} | {detail} |"
            )
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendations = data.get("recommendations") or []
    if not recommendations:
        lines.append("No recommendations are currently available.")
    else:
        for recommendation in recommendations:
            lines.append(f"- {_escape_md_cell(recommendation)}")
    lines.append("")

    footer_parts: list[str] = []
    if simulation_id is not None:
        footer_parts.append(f"Simulation {simulation_id}")
    if project_id is not None:
        footer_parts.append(f"Project {project_id}")
    if footer_parts:
        lines.append("---")
        lines.append("")
        lines.append(f"*{' · '.join(footer_parts)}*")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "launch_checklist_to_csv",
    "launch_checklist_to_json",
    "launch_checklist_to_markdown",
]
