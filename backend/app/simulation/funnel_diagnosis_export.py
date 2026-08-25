"""CSV / JSON / Markdown export helpers for the funnel-diagnosis read.

The funnel-diagnosis endpoint
(``GET /api/v1/simulations/{id}/funnel-diagnosis``) returns a structured
bottleneck diagnosis. This module renders that payload for download:

* CSV — a multi-section spreadsheet (summary, per-stage diagnosis,
  cluster drag, drop triggers, ranked recommendations) so founders can
  keep a record in Sheets/Excel.
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


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
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
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "overall_conversion": data.get("overall_conversion"),
        "total_agents": data.get("total_agents"),
        "converted_agents": data.get("converted_agents"),
        "primary_bottleneck": data.get("primary_bottleneck"),
        "bottleneck_severity": data.get("bottleneck_severity"),
        "health_score": data.get("health_score"),
        "recoverable_conversion": data.get("recoverable_conversion"),
        "primary_failure_domain": data.get("primary_failure_domain"),
        "product_type_detected": data.get("product_type_detected"),
        "signal_quality": data.get("signal_quality"),
    }


def funnel_diagnosis_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a funnel-diagnosis payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Funnel Diagnosis Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_dict(data).items():
        _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, [])

    # Stage diagnosis rows.
    _write_row(writer, ["section", "Stage Diagnosis"])
    _write_row(
        writer,
        [
            "stage",
            "agent_count",
            "entry_rate",
            "drop_off_rate",
            "agents_lost",
            "healthy_drop_off",
            "delta_from_healthy",
            "severity",
            "primary_domain",
            "recommended_architects",
            "is_primary_bottleneck",
        ],
    )
    for stage in data.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        architects = stage.get("recommended_architects") or []
        _write_row(
            writer,
            [
                _safe_text(stage.get("stage")),
                _safe_int(stage.get("agent_count")),
                _safe_float(stage.get("entry_rate")),
                _safe_float(stage.get("drop_off_rate")),
                _safe_int(stage.get("agents_lost")),
                _safe_float(stage.get("healthy_drop_off")),
                _safe_float(stage.get("delta_from_healthy")),
                _safe_text(stage.get("severity")),
                _safe_text(stage.get("primary_domain")),
                "|".join(_safe_text(item) for item in architects),
                "1" if stage.get("is_primary_bottleneck") else "0",
            ],
        )
    _write_row(writer, [])

    # Cluster drag rows.
    _write_row(writer, ["section", "Cluster Drag"])
    _write_row(
        writer,
        [
            "cluster_id",
            "cluster_name",
            "conversion_rate",
            "population_weight",
            "lost_conversion_share",
            "primary_drop_trigger",
            "mean_drop_state",
        ],
    )
    for row in data.get("cluster_drag") or []:
        if not isinstance(row, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(row.get("cluster_id")),
                _safe_text(row.get("cluster_name")),
                _safe_float(row.get("conversion_rate")),
                _safe_float(row.get("population_weight")),
                _safe_float(row.get("lost_conversion_share")),
                _safe_text(row.get("primary_drop_trigger")),
                _safe_text(row.get("mean_drop_state")),
            ],
        )
    _write_row(writer, [])

    # Drop triggers.
    _write_row(writer, ["section", "Drop Triggers"])
    _write_row(
        writer,
        ["trigger", "cluster_count", "agents_affected", "mean_conversion"],
    )
    for row in data.get("drop_triggers") or []:
        if not isinstance(row, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(row.get("trigger")),
                _safe_int(row.get("cluster_count")),
                _safe_int(row.get("agents_affected")),
                _safe_float(row.get("mean_conversion")),
            ],
        )
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(
        writer,
        [
            "priority",
            "stage",
            "domain",
            "severity",
            "title",
            "rationale",
            "estimated_lift",
            "architects",
            "related_clusters",
        ],
    )
    for row in data.get("recommendations") or []:
        if not isinstance(row, dict):
            continue
        architects = row.get("architects") or []
        related = row.get("related_clusters") or []
        _write_row(
            writer,
            [
                _safe_int(row.get("priority")),
                _safe_text(row.get("stage")),
                _safe_text(row.get("domain")),
                _safe_text(row.get("severity")),
                _safe_text(row.get("title")),
                _safe_text(row.get("rationale")),
                _safe_float(row.get("estimated_lift")),
                "|".join(_safe_text(item) for item in architects),
                "|".join(_safe_text(item) for item in related),
            ],
        )
    _write_row(writer, [])

    # Meta key/value section.
    meta = data.get("meta") or {}
    if isinstance(meta, dict) and meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            value = meta[key]
            if isinstance(value, dict):
                _write_row(writer, [key, json.dumps(value, default=str)])
            else:
                _write_row(writer, [key, _safe_text(value)])

    return buffer.getvalue()


def funnel_diagnosis_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a funnel-diagnosis payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "funnel_diagnosis": _as_dict(payload)},
        default=str,
        indent=2,
    )


def _escape_md_cell(value: Any) -> str:
    """Escape pipe and newline characters for a Markdown table cell."""
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def funnel_diagnosis_to_markdown(
    payload: Any,
    *,
    simulation_id: int | None = None,
    project_id: int | None = None,
    project_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a funnel-diagnosis payload as a founder-facing Markdown brief."""
    data = _as_dict(payload)
    title = (project_name or "TheCee").strip() or "TheCee"

    lines: list[str] = []
    lines.append(f"# {_escape_md_cell(title)} — Funnel Diagnosis")
    lines.append("")
    lines.append(
        "This deterministic diagnosis compares the simulated purchase funnel "
        "against healthy drop-off benchmarks and ranks the biggest "
        "opportunities to lift conversion."
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
    lines.append(f"| Overall conversion | {_safe_float(data.get('overall_conversion')):.2%} |")
    lines.append(
        "| Converted agents | "
        f"{_safe_int(data.get('converted_agents'))} "
        f"/ {_safe_int(data.get('total_agents'))} |"
    )
    lines.append(f"| Primary bottleneck | {_escape_md_cell(data.get('primary_bottleneck'))} |")
    lines.append(f"| Bottleneck severity | {_escape_md_cell(data.get('bottleneck_severity'))} |")
    lines.append(f"| Health score | {_safe_int(data.get('health_score'))}/100 |")
    if data.get("recoverable_conversion") is not None:
        lines.append(
            f"| Recoverable conversion | {_safe_float(data.get('recoverable_conversion')):.2%} |"
        )
    if data.get("signal_quality") is not None:
        lines.append(f"| Signal quality | {_safe_float(data.get('signal_quality')):.2f} |")
    if data.get("primary_failure_domain"):
        lines.append(
            f"| Primary failure domain | {_escape_md_cell(data.get('primary_failure_domain'))} |"
        )
    if data.get("product_type_detected"):
        lines.append(f"| Product type | {_escape_md_cell(data.get('product_type_detected'))} |")
    lines.append("")

    lines.append("## Stage Diagnosis")
    lines.append("")
    stages = data.get("stages") or []
    if not stages:
        lines.append("No stage metrics are available.")
    else:
        lines.append(
            "| Stage | Agents | Entry rate | Drop-off | Healthy | Delta | Severity | Bottleneck |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_name = _escape_md_cell(stage.get("stage"))
            entry = _safe_float(stage.get("entry_rate"))
            drop = _safe_float(stage.get("drop_off_rate"))
            healthy = _safe_float(stage.get("healthy_drop_off"))
            delta = _safe_float(stage.get("delta_from_healthy"))
            severity = _escape_md_cell(stage.get("severity"))
            bottleneck = "yes" if stage.get("is_primary_bottleneck") else ""
            lines.append(
                f"| {stage_name} | {_safe_int(stage.get('agent_count'))} | "
                f"{entry:.1%} | {drop:.1%} | {healthy:.1%} | {delta:+.1%} | "
                f"{severity} | {bottleneck} |"
            )
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendations = data.get("recommendations") or []
    if not recommendations:
        lines.append("No recommendations are currently available.")
    else:
        for index, rec in enumerate(recommendations, start=1):
            if not isinstance(rec, dict):
                continue
            title = _escape_md_cell(rec.get("title") or f"Recommendation {index}")
            stage = _escape_md_cell(rec.get("stage"))
            domain = _escape_md_cell(rec.get("domain"))
            severity = _escape_md_cell(rec.get("severity"))
            lift = _safe_float(rec.get("estimated_lift"))
            lines.append(
                f"{index}. **{title}** "
                f"({severity} · {stage} · {domain}) — "
                f"estimated lift {lift:.2%}."
            )
            rationale = _safe_text(rec.get("rationale"))
            if rationale:
                lines.append(f"   {_escape_md_cell(rationale)}")
            related = rec.get("related_clusters") or []
            if related:
                lines.append(
                    "   Related clusters: "
                    + ", ".join(_escape_md_cell(item) for item in related)
                    + "."
                )
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
    "funnel_diagnosis_to_csv",
    "funnel_diagnosis_to_json",
    "funnel_diagnosis_to_markdown",
]
