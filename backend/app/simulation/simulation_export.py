"""
Pure per-simulation export helpers.

Turns a completed simulation's ``results_json`` into a spreadsheet-friendly
row set (one row per cluster) plus a small metadata block, so founders can
download the same numbers they see in the dashboard without re-running the
conductor.

The route layer supplies ``results``, ``cluster_names`` and
``cluster_weights``; this module stays pure and deterministic. Missing or
malformed fields degrade to neutral values instead of crashing the export.
"""
from __future__ import annotations

import csv
import io
import json
import math
from typing import Any


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _clean_signal_quality(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _cluster_rows(
    results: dict[str, Any],
    cluster_names: dict[str, str] | None,
    cluster_weights: dict[str, float] | None,
) -> list[dict[str, Any]]:
    names = cluster_names or {}
    weights = cluster_weights or {}
    breakdown = results.get("cluster_breakdown") or results.get(
        "cluster_summaries"
    ) or {}
    if not isinstance(breakdown, dict):
        return []

    rows: list[dict[str, Any]] = []
    for cluster_id, raw in breakdown.items():
        cid = str(cluster_id)
        conversion: float = 0.0
        weight: float = weights.get(cid, 0.0)
        if isinstance(raw, dict):
            conversion = _safe_float(
                raw.get("conversion_rate", raw.get("conversion", 0.0))
            )
            weight = _safe_float(
                raw.get("population_weight", weight),
                default=weight,
            )
        else:
            conversion = _safe_float(raw, default=0.0)
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": str(names.get(cid, cid)),
                "population_weight": round(max(0.0, weight), 4),
                "conversion_rate": round(max(0.0, min(1.0, conversion)), 4),
            }
        )

    rows.sort(key=lambda row: (-row["population_weight"], row["cluster_id"]))
    return rows


def build_simulation_export(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    product_type: str = "saas",
    signal_quality: float | None = None,
    cluster_names: dict[str, str] | None = None,
    cluster_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compose the per-simulation export payload.

    Args:
        results: Simulation ``results_json``.
        simulation_id: Simulation primary key.
        project_id: Owning project primary key.
        status: Simulation status string.
        product_type: Detected product type for the run.
        signal_quality: Persisted signal quality, if any.
        cluster_names: ``{cluster_id: name}`` lookup.
        cluster_weights: ``{cluster_id: population_weight}`` lookup.
    """
    payload = _coerce_results(results)
    rows = _cluster_rows(payload, cluster_names, cluster_weights)

    conversion_raw = payload.get(
        "population_weighted_conversion",
        payload.get("mean_conversion_rate", payload.get("conversion_rate")),
    )
    conversion = (
        round(max(0.0, min(1.0, _safe_float(conversion_raw))), 4)
        if conversion_raw is not None
        else None
    )

    return {
        "simulation_id": simulation_id,
        "project_id": project_id,
        "status": status,
        "product_type": str(product_type or "saas"),
        "signal_quality": _clean_signal_quality(signal_quality),
        "population_weighted_conversion": conversion,
        "total_clusters": len(rows),
        "rows": rows,
    }


def simulation_to_csv(export: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    """Render an export payload as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", str(metadata.get("generated_at", ""))])
        writer.writerow(["user_id", str(metadata.get("user_id", ""))])
        writer.writerow(["format_version", str(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "simulation_id",
            "project_id",
            "status",
            "product_type",
            "signal_quality",
            "population_weighted_conversion",
            "cluster_id",
            "cluster_name",
            "population_weight",
            "conversion_rate",
        ]
    )
    for row in export.get("rows") or []:
        writer.writerow(
            [
                export.get("simulation_id", ""),
                export.get("project_id", ""),
                export.get("status", ""),
                export.get("product_type", ""),
                export.get("signal_quality", ""),
                export.get("population_weighted_conversion", ""),
                row.get("cluster_id", ""),
                row.get("cluster_name", ""),
                row.get("population_weight", ""),
                row.get("conversion_rate", ""),
            ]
        )
    return buffer.getvalue()


__all__ = [
    "build_simulation_export",
    "simulation_to_csv",
]
