"""CSV/JSON export helpers for the unit-economics analysis.

The route layer in ``app/api/v1/simulations.py`` builds a
:class:`app.schemas.unit_economics.UnitEconomicsOut` payload; this module
renders that payload as a spreadsheet-friendly CSV so founders can bring
the LTV/CAC/payback table into their own models.

The output uses the same lightweight multi-section CSV convention as the
simulation and calibration-health exports: an optional metadata block, a
one-row-per-key summary section, one row per cluster unit economics, the
CAC and price scenario tables, and the recommendation list. Missing
optional fields render as blanks rather than crashing the export.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key, default in (
        ("generated_at", ""),
        ("user_id", ""),
        ("format_version", "1"),
        ("simulation_id", ""),
        ("project_id", ""),
    ):
        value = metadata.get(key, default)
        rows.append((key, "" if value is None else str(value)))
    return rows


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _value(value: Any) -> object:
    return "" if value is None else value


def unit_economics_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a unit-economics payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        write_row(writer, [key, value])
    if metadata:
        write_row(writer, [])

    # Summary section.
    write_row(writer, ["section", "Unit Economics Summary"])
    write_row(writer, ["key", "value"])
    summary_keys = (
        "simulation_id",
        "project_id",
        "status",
        "signal_quality",
        "product_type",
        "aov",
        "gross_margin",
        "purchase_frequency_per_year",
        "base_cac",
        "effective_base_cac",
        "blended_price",
        "blended_monthly_contribution",
        "blended_lifetime_months",
        "blended_ltv",
        "blended_cac",
        "blended_ltv_cac_ratio",
        "blended_payback_months",
        "affordable_cac_ceiling",
        "verdict",
        "strong_share",
        "profitable_share",
        "unprofitable_share",
        "at_ceiling_share",
        "best_cluster_id",
        "best_cluster_name",
        "worst_cluster_id",
        "worst_cluster_name",
        "total_clusters",
        "clusters_with_data",
    )
    for key in summary_keys:
        write_row(writer, [key, _value(data.get(key))])
    write_row(writer, [])

    # Cluster profiles.
    write_row(writer, ["section", "Cluster Unit Economics"])
    write_row(
        writer,
        [
            "cluster_id",
            "cluster_name",
            "population_weight",
            "conversion_rate",
            "demand_weight",
            "effective_price",
            "price_ceiling",
            "will_pay_probability",
            "monthly_contribution",
            "average_lifetime_months",
            "ltv",
            "cac",
            "cac_multiplier",
            "primary_channel",
            "ltv_cac_ratio",
            "payback_months",
            "affordable_cac",
            "verdict",
        ],
    )
    cluster_keys = (
        "cluster_id",
        "cluster_name",
        "population_weight",
        "conversion_rate",
        "demand_weight",
        "effective_price",
        "price_ceiling",
        "will_pay_probability",
        "monthly_contribution",
        "average_lifetime_months",
        "ltv",
        "cac",
        "cac_multiplier",
        "primary_channel",
        "ltv_cac_ratio",
        "payback_months",
        "affordable_cac",
        "verdict",
    )
    for profile in data.get("cluster_profiles") or []:
        if not isinstance(profile, dict):
            continue
        write_row(writer, [_value(profile.get(key)) for key in cluster_keys])
    write_row(writer, [])

    # CAC scenarios.
    write_row(writer, ["section", "CAC Scenarios"])
    write_row(writer, ["label", "cac_multiplier", "blended_cac", "blended_ltv_cac_ratio"])
    for scenario in data.get("cac_scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        write_row(
            writer,
            [
                scenario.get("label", ""),
                scenario.get("cac_multiplier", ""),
                scenario.get("blended_cac", ""),
                scenario.get("blended_ltv_cac_ratio", ""),
            ],
        )
    write_row(writer, [])

    # Price scenarios.
    write_row(writer, ["section", "Price Scenarios"])
    write_row(
        writer,
        [
            "label",
            "price_multiplier",
            "blended_price",
            "blended_ltv",
            "blended_ltv_cac_ratio",
            "capped_share",
        ],
    )
    for scenario in data.get("price_scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        write_row(
            writer,
            [
                scenario.get("label", ""),
                scenario.get("price_multiplier", ""),
                scenario.get("blended_price", ""),
                scenario.get("blended_ltv", ""),
                scenario.get("blended_ltv_cac_ratio", ""),
                scenario.get("capped_share", ""),
            ],
        )
    write_row(writer, [])

    # Recommendations.
    write_row(writer, ["section", "Recommendations"])
    write_row(writer, ["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            write_row(writer, [recommendation])
    else:
        write_row(writer, [""])

    return buffer.getvalue()


__all__ = ["unit_economics_to_csv"]
