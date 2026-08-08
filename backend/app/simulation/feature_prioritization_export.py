"""CSV / JSON / Markdown export helpers for the feature-prioritization read.

The feature-prioritization endpoint
(``GET /api/v1/simulations/{id}/feature-prioritization``) answers the
founder's "which features should I build or polish first?" question. This
module renders that same deterministic payload for download:

* CSV — a multi-section spreadsheet (summary, prioritized dimensions,
  cluster feature profiles, brief-feature mapping, flags, recommendations)
  so founders can sort and plan in Sheets/Excel.
* JSON — a machine-readable envelope for tools and integrations.
* Markdown — a concise founder-facing brief for docs, Notion, or an
  investor update.

The module stays pure and defensive: missing fields, malformed rows, and
unsupported tiers degrade to safe defaults without raising.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any


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
    writer.writerow([_safe_csv_cell(value) for value in row])


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
    """Flatten top-level fields plus meta into the summary section."""
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "product_type": data.get("product_type"),
        "verdict": data.get("verdict"),
        "signal_quality": meta.get("signal_quality"),
        "total_clusters": meta.get("total_clusters"),
        "covered_clusters": meta.get("covered_clusters"),
        "covered_weight": meta.get("covered_weight"),
        "top_dimension": meta.get("top_dimension"),
        "top_priority_score": meta.get("top_priority_score"),
        "product_type_supported": meta.get("product_type_supported"),
        "dimension_count": len(data.get("dimensions") or []),
        "cluster_profiles_count": len(data.get("cluster_profiles") or []),
        "brief_features_count": len(data.get("brief_features") or []),
        "flags_count": len(data.get("flags") or []),
        "recommendations_count": len(data.get("recommendations") or []),
    }


def feature_prioritization_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a feature-prioritization payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Feature Prioritization Summary"])
    _write_row(writer, ["key", "value"])
    summary_values = _summary_dict(data)
    for key, value in summary_values.items():
        _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, [])

    # Prioritized dimensions.
    _write_row(writer, ["section", "Prioritized Dimensions"])
    _write_row(
        writer,
        [
            "key",
            "label",
            "adoption_rate",
            "reach_weight",
            "upside",
            "priority_score",
            "priority_tier",
            "recommendation",
        ],
    )
    for item in data.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("key")),
                _safe_text(item.get("label")),
                _safe_float(item.get("adoption_rate")),
                _safe_float(item.get("reach_weight")),
                _safe_float(item.get("upside")),
                _safe_float(item.get("priority_score")),
                _safe_text(item.get("priority_tier")),
                _safe_text(item.get("recommendation")),
            ],
        )
    _write_row(writer, [])

    # Cluster feature profiles.
    _write_row(writer, ["section", "Cluster Feature Profiles"])
    _write_row(
        writer,
        [
            "cluster_id",
            "cluster_name",
            "population_weight",
            "feature_depth",
            "core_dau_rate",
            "power_discovery_rate",
            "abandonment_rate",
            "segment_tier",
        ],
    )
    for item in data.get("cluster_profiles") or []:
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("cluster_id")),
                _safe_text(item.get("cluster_name")),
                _safe_float(item.get("population_weight")),
                _safe_float(item.get("feature_depth")),
                _safe_float(item.get("core_dau_rate")),
                _safe_float(item.get("power_discovery_rate")),
                _safe_float(item.get("abandonment_rate")),
                _safe_text(item.get("segment_tier")),
            ],
        )
    _write_row(writer, [])

    # Brief feature mapping.
    _write_row(writer, ["section", "Brief Feature Mapping"])
    _write_row(
        writer,
        [
            "feature",
            "dimension_key",
            "dimension_label",
            "adoption_rate",
            "priority_tier",
            "note",
        ],
    )
    for item in data.get("brief_features") or []:
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("feature")),
                _safe_text(item.get("dimension_key")),
                _safe_text(item.get("dimension_label")),
                _safe_float(item.get("adoption_rate")),
                _safe_text(item.get("priority_tier")),
                _safe_text(item.get("note")),
            ],
        )
    _write_row(writer, [])

    # Flags.
    _write_row(writer, ["section", "Flags"])
    _write_row(writer, ["flag"])
    flags = data.get("flags") or []
    if flags:
        for flag in flags:
            _write_row(writer, [_safe_text(flag)])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(writer, ["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            _write_row(writer, [_safe_text(recommendation)])
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


def feature_prioritization_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a feature-prioritization payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "feature_prioritization": _as_dict(payload),
        },
        default=str,
        indent=2,
    )


def _escape_md_cell(value: Any) -> str:
    """Escape pipe and newline characters for a Markdown table cell."""
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _fmt_pct(value: Any) -> str:
    parsed = _safe_float(value)
    return f"{max(0.0, min(1.0, parsed)) * 100:.0f}%"


def feature_prioritization_to_markdown(
    payload: Any,
    *,
    simulation_id: int | None = None,
    project_id: int | None = None,
    project_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a feature-prioritization payload as a founder-facing brief."""
    data = _as_dict(payload)
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    title = (project_name or "TheCee").strip() or "TheCee"
    lines: list[str] = []
    lines.append(f"# {_escape_md_cell(title)} — Feature Prioritization")
    lines.append("")
    lines.append(
        "This deterministic ranking maps validated adoption, unserved "
        "headroom, and product-type strategy to the features most worth "
        "building or polishing next."
    )
    lines.append("")

    if metadata:
        generated_at = metadata.get("generated_at", "")
        lines.append(f"- Generated: {_escape_md_cell(generated_at)}")
    lines.append(f"- Simulation: {simulation_id or '—'}")
    lines.append(f"- Project: {project_id or '—'}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Key | Value |")
    lines.append("| --- | --- |")
    summary_values = _summary_dict(data)
    for key, value in summary_values.items():
        lines.append(f"| {_escape_md_cell(key)} | {_escape_md_cell(value)} |")
    lines.append("")

    lines.append("## Prioritized Dimensions")
    lines.append("")
    dimensions = data.get("dimensions") or []
    if dimensions:
        lines.append(
            "| Dimension | Adoption | Reach | Upside | Score | Tier | Recommendation |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for item in dimensions:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {label} | {adoption} | {reach} | {upside} | {score} | "
                "{tier} | {rec} |".format(
                    label=_escape_md_cell(item.get("label")),
                    adoption=_fmt_pct(item.get("adoption_rate")),
                    reach=_fmt_pct(item.get("reach_weight")),
                    upside=_fmt_pct(item.get("upside")),
                    score=f"{_safe_float(item.get('priority_score')):.4f}",
                    tier=_escape_md_cell(item.get("priority_tier")),
                    rec=_escape_md_cell(item.get("recommendation")),
                )
            )
    else:
        lines.append("No modeled feature dimensions are available.")
    lines.append("")

    lines.append("## Cluster Feature Profiles")
    lines.append("")
    profiles = data.get("cluster_profiles") or []
    if profiles:
        lines.append(
            "| Cluster | Weight | Depth | Core DAU | Power Discovery | "
            "Abandonment | Segment |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for item in profiles:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {name} | {weight} | {depth} | {core} | {power} | "
                "{abandon} | {segment} |".format(
                    name=_escape_md_cell(item.get("cluster_name")),
                    weight=f"{_safe_float(item.get('population_weight')):.4f}",
                    depth=_fmt_pct(item.get("feature_depth")),
                    core=_fmt_pct(item.get("core_dau_rate")),
                    power=_fmt_pct(item.get("power_discovery_rate")),
                    abandon=_fmt_pct(item.get("abandonment_rate")),
                    segment=_escape_md_cell(item.get("segment_tier")),
                )
            )
    else:
        lines.append("No cluster feature profiles are available.")
    lines.append("")

    lines.append("## Brief Feature Mapping")
    lines.append("")
    brief = data.get("brief_features") or []
    if brief:
        lines.append(
            "| Feature | Dimension | Adoption | Tier | Note |"
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for item in brief:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {feature} | {dimension} | {adoption} | {tier} | {note} |".format(
                    feature=_escape_md_cell(item.get("feature")),
                    dimension=_escape_md_cell(item.get("dimension_label")),
                    adoption=(
                        _fmt_pct(item.get("adoption_rate"))
                        if item.get("adoption_rate") is not None
                        else "—"
                    ),
                    tier=_escape_md_cell(item.get("priority_tier")),
                    note=_escape_md_cell(item.get("note")),
                )
            )
    else:
        lines.append("No founder-declared brief features were mapped.")
    lines.append("")

    lines.append("## Flags")
    lines.append("")
    flags = data.get("flags") or []
    if flags:
        for flag in flags:
            lines.append(f"- {_escape_md_cell(flag)}")
    else:
        lines.append("No risk flags detected.")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendations = data.get("recommendations") or []
    if recommendations:
        for index, recommendation in enumerate(recommendations, start=1):
            lines.append(f"{index}. {_escape_md_cell(recommendation)}")
    else:
        lines.append("No recommendations are currently available.")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "feature_prioritization_to_csv",
    "feature_prioritization_to_json",
    "feature_prioritization_to_markdown",
]
