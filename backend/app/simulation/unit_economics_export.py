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
        writer.writerow([key, value])
    if metadata:
        writer.writerow([])

    # Summary section.
    writer.writerow(["section", "Unit Economics Summary"])
    writer.writerow(["key", "value"])
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
        writer.writerow([key, _value(data.get(key))])
    writer.writerow([])

    # Cluster profiles.
    writer.writerow(["section", "Cluster Unit Economics"])
    writer.writerow(
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
        ]
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
        writer.writerow([_value(profile.get(key)) for key in cluster_keys])
    writer.writerow([])

    # CAC scenarios.
    writer.writerow(["section", "CAC Scenarios"])
    writer.writerow(
        ["label", "cac_multiplier", "blended_cac", "blended_ltv_cac_ratio"]
    )
    for scenario in data.get("cac_scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        writer.writerow(
            [
                scenario.get("label", ""),
                scenario.get("cac_multiplier", ""),
                scenario.get("blended_cac", ""),
                scenario.get("blended_ltv_cac_ratio", ""),
            ]
        )
    writer.writerow([])

    # Price scenarios.
    writer.writerow(["section", "Price Scenarios"])
    writer.writerow(
        [
            "label",
            "price_multiplier",
            "blended_price",
            "blended_ltv",
            "blended_ltv_cac_ratio",
            "capped_share",
        ]
    )
    for scenario in data.get("price_scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        writer.writerow(
            [
                scenario.get("label", ""),
                scenario.get("price_multiplier", ""),
                scenario.get("blended_price", ""),
                scenario.get("blended_ltv", ""),
                scenario.get("blended_ltv_cac_ratio", ""),
                scenario.get("capped_share", ""),
            ]
        )
    writer.writerow([])

    # Recommendations.
    writer.writerow(["section", "Recommendations"])
    writer.writerow(["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            writer.writerow([recommendation])
    else:
        writer.writerow([""])

    return buffer.getvalue()


__all__ = ["unit_economics_to_csv"]
