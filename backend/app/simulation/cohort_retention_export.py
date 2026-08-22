"""CSV, JSON, and Markdown exports for the cohort-retention projection.

``GET /simulations/{id}/cohort-retention`` answers *who stays, who churns,
and what is that worth?*; these exports put the projection in a founder's
spreadsheet, data pipeline, or board update.  Formatting is pure and reuses
the exact ``CohortRetentionOut`` payload produced by the endpoint — no
recomputation happens here.

CSV is a multi-section document: metadata header, a retention overview,
the churn-trigger distribution, one row per cluster profile, the full
per-day retention-curve points, segment summaries, and recommendations.
Cells are guarded against spreadsheet formula injection.  JSON is an
envelope with stable metadata and the unmodified payload.  Markdown is a
founder-facing brief with headline numbers, segments, clusters, and the
recommendation list.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_OVERVIEW_KEYS: tuple[str, ...] = (
    "simulation_id",
    "project_id",
    "status",
    "overall_conversion",
    "total_agents",
    "total_converted",
    "market_day30_survival",
    "market_day90_survival",
    "market_day365_survival",
    "highest_churn_stage",
    "best_retention_cluster",
    "worst_retention_cluster",
    "reengagement_viable",
    "product_type_detected",
    "primary_failure_domain",
    "signal_quality",
)

_PROFILE_HEADERS: tuple[str, ...] = (
    "cluster_id",
    "cluster_name",
    "population_weight",
    "conversion_rate",
    "agents_converted",
    "day30_survival",
    "day90_survival",
    "churn_risk",
    "churn_trigger",
    "ltv_score",
    "ltv_estimate",
    "reengagement_viable",
    "reengagement_prob_30d",
)

_CURVE_HEADERS: tuple[str, ...] = (
    "cluster_id",
    "day",
    "survival_rate",
    "cumulative_churn",
    "active_users",
)

_SEGMENT_HEADERS: tuple[str, ...] = (
    "segment",
    "cluster_count",
    "total_population_weight",
    "mean_day30_survival",
    "mean_day90_survival",
    "mean_ltv_score",
    "mean_churn_risk_score",
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


def _csv_cell(value: Any) -> object:
    """Keep real numbers native; guard formula-leading strings."""
    if isinstance(value, bool):
        return _text(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return value
    return _safe_csv_cell(_text(value))


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
    writer.writerow([_csv_cell(value) for value in row])


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
            "simulation_id",
            "project_id",
            "format_version",
        )
    ]


def cohort_retention_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cohort-retention payload as a multi-section CSV."""
    data = _as_dict(payload)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Retention Overview"])
    _write_row(writer, ["key", "value"])
    for key in _OVERVIEW_KEYS:
        value = data.get(key)
        _write_row(writer, [key, _csv_cell(value)])
    _write_row(writer, [])

    triggers = _as_dict(data.get("churn_trigger_distribution"))
    if triggers:
        _write_row(writer, ["section", "Churn Triggers"])
        _write_row(writer, ["trigger", "count"])
        for key in sorted(triggers):
            _write_row(writer, [key, _csv_cell(triggers[key])])
        _write_row(writer, [])

    profiles = data.get("cluster_profiles") or []
    _write_row(writer, ["section", "Cluster Profiles"])
    _write_row(writer, list(_PROFILE_HEADERS))
    for raw in profiles:
        row = _as_dict(raw)
        _write_row(
            writer,
            [_csv_cell(row.get(key)) for key in _PROFILE_HEADERS],
        )
    _write_row(writer, [])

    curve_rows: list[list[object]] = []
    for raw in profiles:
        row = _as_dict(raw)
        cluster_id = _text(row.get("cluster_id"))
        for point in row.get("retention_curve") or []:
            point_data = _as_dict(point)
            curve_rows.append(
                [cluster_id]
                + [_csv_cell(point_data.get(key)) for key in _CURVE_HEADERS[1:]]
            )
    if curve_rows:
        _write_row(writer, ["section", "Retention Curve Points"])
        _write_row(writer, list(_CURVE_HEADERS))
        for curve_row in curve_rows:
            writer.writerow(curve_row)
        _write_row(writer, [])

    segments = data.get("segment_summary") or []
    if segments:
        _write_row(writer, ["section", "Segment Summary"])
        _write_row(writer, list(_SEGMENT_HEADERS))
        for raw in segments:
            row = _as_dict(raw)
            _write_row(
                writer,
                [_csv_cell(row.get(key)) for key in _SEGMENT_HEADERS],
            )
        _write_row(writer, [])

    recommendations = data.get("recommendations") or []
    if recommendations:
        _write_row(writer, ["section", "Recommendations"])
        for text in recommendations:
            _write_row(writer, [text])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _csv_cell(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def cohort_retention_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cohort-retention payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "cohort_retention": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    """Escape pipes/newlines so cells can't break Markdown tables."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def _md_pct(value: Any) -> str:
    """Format a fraction as a percentage, or return a dash."""
    if value is None:
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    if not math.isfinite(fraction):
        return "—"
    return f"{fraction * 100:.1f}%"


def _md_date(value: Any) -> str:
    """Render a timestamp as a founder-friendly date in the brief."""
    if value is None or value == "":
        return "—"
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except (TypeError, ValueError):
            pass
    text = str(value)
    return _escape_md_cell(text.split("T", 1)[0].split(" ", 1)[0])


def _trigger_count(value: Any) -> int:
    """Coerce a churn-trigger histogram count for sorting."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def cohort_retention_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cohort-retention payload as a founder-facing brief."""
    data = _as_dict(payload)
    profiles = data.get("cluster_profiles") or []
    segments = data.get("segment_summary") or []
    recommendations = data.get("recommendations") or []

    lines: list[str] = []
    lines.append("# Cohort Retention")
    lines.append("")
    lines.append(
        "Projected survival, churn risk, and lifetime value across the "
        "simulated consumer clusters."
    )
    lines.append("")

    if metadata and metadata.get("generated_at"):
        lines.append(f"*Generated: {_md_date(metadata['generated_at'])}*")
        lines.append("")

    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    overview_labels = (
        ("overall_conversion", "Overall conversion"),
        ("total_agents", "Agents simulated"),
        ("total_converted", "Agents converted"),
        ("market_day30_survival", "Day-30 survival"),
        ("market_day90_survival", "Day-90 survival"),
        ("market_day365_survival", "Day-365 survival"),
        ("highest_churn_stage", "Highest churn stage"),
        ("best_retention_cluster", "Best retention cluster"),
        ("product_type_detected", "Product type"),
        ("primary_failure_domain", "Primary failure domain"),
    )
    for key, label in overview_labels:
        value = data.get(key)
        rendered = (
            _md_pct(value)
            if key
            in (
                "overall_conversion",
                "market_day30_survival",
                "market_day90_survival",
                "market_day365_survival",
            )
            else _md_cell(value)
        )
        lines.append(f"| {label} | {rendered} |")
    lines.append("")

    worst = _text(data.get("worst_retention_cluster"))
    if worst:
        lines.append(f"**Weakest cohort: {_escape_md_cell(worst)}**")
        lines.append("")

    viable_count = sum(
        1 for raw in profiles if _as_dict(raw).get("reengagement_viable")
    )
    if profiles and viable_count:
        lines.append(
            f"*{viable_count} of {len(profiles)} clusters remain "
            "re-engagement viable.*"
        )
        lines.append("")

    triggers = _as_dict(data.get("churn_trigger_distribution"))
    if triggers:
        lines.append("## Churn Triggers")
        lines.append("")
        lines.append("| Trigger | Clusters |")
        lines.append("| --- | --- |")
        for trigger, count in sorted(
            triggers.items(), key=lambda kv: (-_trigger_count(kv[1]), str(kv[0]))
        ):
            lines.append(f"| {_escape_md_cell(trigger)} | {_md_cell(count)} |")
        lines.append("")

    if segments:
        lines.append("## Segments")
        lines.append("")
        lines.append(
            "| Segment | Clusters | Day-30 | Day-90 | Mean LTV score |"
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for raw in segments:
            row = _as_dict(raw)
            cells = [
                _escape_md_cell(row.get("segment")),
                _md_cell(row.get("cluster_count")),
                _md_pct(row.get("mean_day30_survival")),
                _md_pct(row.get("mean_day90_survival")),
                _md_cell(row.get("mean_ltv_score")),
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## Cluster Profiles")
    lines.append("")
    if not profiles:
        lines.append("_No cluster profiles returned._")
    else:
        lines.append(
            "| Cluster | Conversion | Day-30 | Day-90 | Churn risk | LTV estimate | Re-engage? |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for raw in profiles:
            row = _as_dict(raw)
            name = _text(row.get("cluster_name")) or _text(row.get("cluster_id"))
            cells = [
                _escape_md_cell(name),
                _md_pct(row.get("conversion_rate")),
                _md_pct(row.get("day30_survival")),
                _md_pct(row.get("day90_survival")),
                _escape_md_cell(row.get("churn_risk")),
                _md_cell(row.get("ltv_estimate")),
                "yes" if row.get("reengagement_viable") else "no",
            ]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    if recommendations:
        lines.append("## Recommendations")
        lines.append("")
        for text in recommendations:
            lines.append(f"- {_escape_md_cell(text)}")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Cohort retention"]
    simulation_id = _text(data.get("simulation_id"))
    if not simulation_id and metadata:
        simulation_id = _text(metadata.get("simulation_id"))
    if simulation_id:
        footer.append(f"Simulation {simulation_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(f"Generated {_md_date(metadata['generated_at'])}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "cohort_retention_to_csv",
    "cohort_retention_to_json",
    "cohort_retention_to_markdown",
]
