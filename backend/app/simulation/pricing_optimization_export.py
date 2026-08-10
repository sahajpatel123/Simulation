"""CSV / JSON / Markdown export helpers for the pricing-optimization read.

The pricing-optimization endpoint
(``GET /api/v1/simulations/{id}/pricing-optimization``) answers the
founder's "should I charge more or less?" question from a completed run.
This module renders that deterministic payload for download:

* CSV — a multi-section spreadsheet (summary, demand curve, cluster
  willingness-to-pay profiles, recommendations, key signals, metadata) so
  founders can sort and model the curve in Sheets/Excel.
* JSON — a machine-readable envelope for tools and integrations.
* Markdown — a concise founder-facing brief for docs, Notion, or an
  investor update.

The module stays pure and defensive: missing fields, malformed rows, and
scalar values in list sections degrade to safe defaults without raising.
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
    """Coerce an optional sequence to a list, dropping malformed scalars."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


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
    for key, default in (
        ("generated_at", ""),
        ("user_id", ""),
        ("format_version", FORMAT_VERSION),
        ("simulation_id", ""),
        ("project_id", ""),
    ):
        value = metadata.get(key, default)
        rows.append((key, "" if value is None else str(value)))
    return rows


def _summary_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten top-level pricing fields plus selected meta into a summary."""
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "product_type": data.get("product_type"),
        "verdict": data.get("verdict"),
        "aov": data.get("aov"),
        "base_price": data.get("base_price"),
        "base_market_conversion": data.get("base_market_conversion"),
        "base_market_revenue": data.get("base_market_revenue"),
        "revenue_optimal_price": data.get("revenue_optimal_price"),
        "revenue_at_optimal": data.get("revenue_at_optimal"),
        "revenue_lift_vs_base_pct": data.get("revenue_lift_vs_base_pct"),
        "recommended_price": data.get("recommended_price"),
        "overall_elasticity": data.get("overall_elasticity"),
        "signal_quality": meta.get("signal_quality"),
        "cohort_size": meta.get("cohort_size"),
        "total_clusters": meta.get("total_clusters"),
        "clusters_with_data": meta.get("clusters_with_data"),
        "covered_weight": meta.get("covered_weight"),
        "demand_retention_rule": meta.get("demand_retention_rule"),
        "elasticity_measurement": meta.get("elasticity_measurement"),
        "demand_curve_points": len(_as_list(data.get("price_points"))),
        "cluster_profiles_count": len(_as_list(data.get("cluster_profiles"))),
        "recommendations_count": len(_as_list(data.get("recommendations"))),
    }


def _row_value(value: Any) -> object:
    """Blank out ``None`` so CSV cells stay empty instead of 'None'."""
    return "" if value is None else value


def pricing_optimization_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a pricing-optimization payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Pricing Optimization Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_dict(data).items():
        _write_row(writer, [key, _row_value(value)])
    _write_row(writer, [])

    # Demand curve.
    _write_row(writer, ["section", "Demand Curve"])
    _write_row(
        writer,
        [
            "price",
            "market_conversion",
            "market_revenue",
            "demand_retained_pct",
        ],
    )
    for item in _as_list(data.get("price_points")):
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_float(item.get("price")),
                _safe_float(item.get("market_conversion")),
                _safe_float(item.get("market_revenue")),
                _safe_float(item.get("demand_retained_pct")),
            ],
        )
    _write_row(writer, [])

    # Cluster willingness-to-pay profiles.
    _write_row(writer, ["section", "Cluster Price Profiles"])
    _write_row(
        writer,
        [
            "cluster_id",
            "cluster_name",
            "population_weight",
            "price_ceiling",
            "will_pay_probability",
            "conversion_at_base_price",
            "optimal_price",
            "at_ceiling",
            "ceiling_gap_pct",
        ],
    )
    for item in _as_list(data.get("cluster_profiles")):
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("cluster_id")),
                _safe_text(item.get("cluster_name")),
                _safe_float(item.get("population_weight")),
                _safe_float(item.get("price_ceiling")),
                _safe_float(item.get("will_pay_probability")),
                _safe_float(item.get("conversion_at_base_price")),
                _safe_float(item.get("optimal_price")),
                _safe_text(item.get("at_ceiling")),
                _safe_float(item.get("ceiling_gap_pct")),
            ],
        )
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(writer, ["recommendation"])
    recommendations = _as_list(data.get("recommendations"))
    if recommendations:
        for recommendation in recommendations:
            _write_row(writer, [_safe_text(recommendation)])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    # Key signals.
    _write_row(writer, ["section", "Key Signals"])
    _write_row(writer, ["label", "value", "severity", "display"])
    for item in _as_list(data.get("key_signals")):
        if not isinstance(item, dict):
            continue
        _write_row(
            writer,
            [
                _safe_text(item.get("label")),
                _row_value(item.get("value")),
                _safe_text(item.get("severity")),
                _safe_text(item.get("display")),
            ],
        )
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
                _write_row(writer, [key, _row_value(value)])

    return buffer.getvalue()


def pricing_optimization_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a pricing-optimization payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "pricing_optimization": _as_dict(payload),
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


def _fmt_price(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed == 0.0 and value not in (0, 0.0, "0", "0.0"):
        return "—"
    return f"{parsed:,.2f}"


def pricing_optimization_to_markdown(
    payload: Any,
    *,
    simulation_id: int | None = None,
    project_id: int | None = None,
    project_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a pricing-optimization payload as a founder-facing brief."""
    data = _as_dict(payload)
    title = (project_name or "TheCee").strip() or "TheCee"
    lines: list[str] = []
    lines.append(f"# {_escape_md_cell(title)} — Pricing Optimization")
    lines.append("")
    lines.append(
        "This deterministic read maps willingness-to-pay ceilings, an "
        "AOV-relative demand curve, and the revenue-optimal price so you "
        "can decide whether to charge more or less."
    )
    lines.append("")

    if metadata:
        generated_at = metadata.get("generated_at", "")
        lines.append(f"- Generated: {_escape_md_cell(generated_at)}")
    lines.append(
        f"- Simulation: "
        f"{simulation_id if simulation_id is not None else '—'}"
    )
    lines.append(
        f"- Project: "
        f"{project_id if project_id is not None else '—'}"
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Key | Value |")
    lines.append("| --- | --- |")
    for key, value in _summary_dict(data).items():
        lines.append(f"| {_escape_md_cell(key)} | {_escape_md_cell(value)} |")
    lines.append("")

    lines.append("## Demand Curve")
    lines.append("")
    points = _as_list(data.get("price_points"))
    if points:
        lines.append(
            "| Price | Market Conversion | Market Revenue | Demand Retained |"
        )
        lines.append("| --- | --- | --- | --- |")
        for item in points:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {price} | {conversion} | {revenue} | {retained} |".format(
                    price=_fmt_price(item.get("price")),
                    conversion=_fmt_pct(item.get("market_conversion")),
                    revenue=_fmt_price(item.get("market_revenue")),
                    retained=(
                        f"{_safe_float(item.get('demand_retained_pct')):.1f}%"
                    ),
                )
            )
    else:
        lines.append("No demand-curve points are available.")
    lines.append("")

    lines.append("## Cluster Price Profiles")
    lines.append("")
    profiles = _as_list(data.get("cluster_profiles"))
    if profiles:
        lines.append(
            "| Cluster | Weight | Ceiling | Will-Pay | Base Conversion | "
            "Optimal Price | At Ceiling | Ceiling Gap |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in profiles:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {name} | {weight} | {ceiling} | {will_pay} | {conv} | "
                "{optimal} | {at_ceiling} | {gap} |".format(
                    name=_escape_md_cell(item.get("cluster_name")),
                    weight=f"{_safe_float(item.get('population_weight')):.4f}",
                    ceiling=_fmt_price(item.get("price_ceiling")),
                    will_pay=_fmt_pct(item.get("will_pay_probability")),
                    conv=_fmt_pct(item.get("conversion_at_base_price")),
                    optimal=_fmt_price(item.get("optimal_price")),
                    at_ceiling=(
                        "Yes" if bool(item.get("at_ceiling")) else "No"
                    ),
                    gap=(
                        f"{_safe_float(item.get('ceiling_gap_pct')):.1f}%"
                    ),
                )
            )
    else:
        lines.append("No cluster price profiles are available.")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendations = _as_list(data.get("recommendations"))
    if recommendations:
        for index, recommendation in enumerate(recommendations, start=1):
            lines.append(f"{index}. {_escape_md_cell(recommendation)}")
    else:
        lines.append("No recommendations are currently available.")
    lines.append("")

    lines.append("## Key Signals")
    lines.append("")
    signals = _as_list(data.get("key_signals"))
    if signals:
        for item in signals:
            if not isinstance(item, dict):
                continue
            display = _safe_text(item.get("display"))
            if display:
                lines.append(f"- {_escape_md_cell(display)}")
    else:
        lines.append("No key signals are currently available.")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "FORMAT_VERSION",
    "pricing_optimization_to_csv",
    "pricing_optimization_to_json",
    "pricing_optimization_to_markdown",
]
