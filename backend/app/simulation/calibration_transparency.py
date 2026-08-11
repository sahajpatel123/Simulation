"""Pure helpers for the per-simulation calibration transparency view.

The Conductor applies learned ``architect_corrections`` rows to every
eligible architect output before the Markov funnel, but the persisted
results only count how many corrections were applied — not which
architects / clusters were affected or how strongly. This module turns
the current ``architect_corrections`` table for a run's product type
into a founder-readable transparency payload:

* eligibility — how many (architect, cluster) pairs the product type's
  deterministic stack evaluates, and how many currently have a learned
  correction;
* per-architect coverage (corrected clusters, average / min / max
  scalar, confidence and sample-weight rollup);
* per-cluster coverage (which clusters are most influenced by the
  learning layer);
* the most influential correction rows, sorted by ``|scalar - 1|`` so
  the strongest adjustments surface first.

The helper is pure: the route supplies the raw ``architect_corrections``
rows and the cluster / architect-stack metadata, and all arithmetic is
deterministic and defensively sanitised so one malformed row can never
poison the response.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from app.simulation.correction_application import (
    Correction,
    best_correction_for_architect_cluster,
    index_corrections,
)

DIRECTION_RAISES: str = "RAISES"
DIRECTION_LOWERS: str = "LOWERS"
DIRECTION_NEUTRAL: str = "NEUTRAL"

DEFAULT_CORRECTIONS_LIMIT: int = 50
MAX_CORRECTIONS_LIMIT: int = 200


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a value to a finite float, falling back to ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative int, falling back to ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


def _cluster_id(cluster: Any) -> str:
    """Return a stable cluster id from a definition or plain string."""
    if isinstance(cluster, str):
        return cluster
    value = getattr(cluster, "cluster_id", None)
    if value is None:
        return str(cluster)
    return str(value)


def _cluster_name(cluster: Any) -> str:
    """Return a display name, falling back to the cluster id."""
    if isinstance(cluster, str):
        return cluster
    name = getattr(cluster, "name", None)
    return str(name) if name is not None else _cluster_id(cluster)


def _correction_row(
    correction: Correction,
    *,
    target_cluster_id: str,
) -> dict[str, Any]:
    """Render one applied correction into a schema-safe dict."""
    return {
        "architect_name": correction.architect_name,
        "cluster_id": target_cluster_id,
        "source_cluster_id": correction.cluster_id,
        "product_type": str(correction.product_type or ""),
        "product_attribute": str(correction.product_attribute or "ALL"),
        "correction_scalar": round(
            max(0.0, _safe_float(correction.correction_scalar, 1.0)),
            6,
        ),
        "confidence_weight": round(
            min(1.0, max(0.0, _safe_float(correction.confidence_weight))),
            6,
        ),
        "effective_sample_count": round(
            max(0.0, _safe_float(correction.effective_sample_count)),
            4,
        ),
        "scope": str(correction.scope or ""),
    }


def _direction(scalars: Sequence[float]) -> str:
    """Classify the mean scalar as raising, lowering, or neutral."""
    if not scalars:
        return DIRECTION_NEUTRAL
    mean = sum(scalars) / len(scalars)
    tolerance = 1e-9
    if mean > 1.0 + tolerance:
        return DIRECTION_RAISES
    if mean < 1.0 - tolerance:
        return DIRECTION_LOWERS
    return DIRECTION_NEUTRAL


def coerce_recorded_applied_corrections(value: Any) -> int | None:
    """Coerce a conductor diagnostics count to a non-negative int.

    The Conductor persists ``applied_corrections`` as an int, but legacy
    or hand-edited ``results_json`` may store a JSON float or numeric
    string. Accept only whole, non-negative numbers so a malformed
    diagnostic can never 500 the endpoint; return ``None`` otherwise.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            return None
        parsed = int(value)
        return parsed if parsed >= 0 else None
    if isinstance(value, str):
        try:
            parsed_float = float(value.strip())
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed_float) or parsed_float != int(parsed_float):
            return None
        parsed = int(parsed_float)
        return parsed if parsed >= 0 else None
    return None


def build_calibration_transparency(
    correction_rows: Sequence[Mapping[str, Any]] | None,
    *,
    product_type: str,
    clusters: Sequence[Any] | None,
    architect_names: Sequence[str] | None,
    simulation_id: int,
    project_id: int,
    corrections_limit: int = DEFAULT_CORRECTIONS_LIMIT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compose the calibration transparency payload for one simulation.

    Args:
        correction_rows: raw ``architect_corrections`` rows for the run's
            product type (same fields :func:`index_corrections` accepts).
        product_type: the run's detected product type.
        clusters: sequence of cluster definitions (or plain cluster ids).
        architect_names: deterministic architect stack for the product
            type, in evaluation order.
        simulation_id / project_id: ownership metadata echoed back.
        corrections_limit: maximum number of strongest correction rows to
            return (default 50, capped at 200 by callers / schema).
        generated_at: ISO timestamp for the payload; defaults to now UTC.

    Returns:
        A dict matching ``CalibrationTransparencyOut``. Never raises:
        empty / malformed input produces a zeroed payload.
    """
    limit = max(1, min(MAX_CORRECTIONS_LIMIT, _safe_int(corrections_limit, 50)))
    cluster_list = list(clusters or [])
    stack = [str(name) for name in (architect_names or []) if str(name).strip()]
    cluster_ids = [_cluster_id(cluster) for cluster in cluster_list]
    indexed = index_corrections(correction_rows, product_type)

    applied: list[dict[str, Any]] = []
    for cluster_id in cluster_ids:
        for architect_name in stack:
            correction = best_correction_for_architect_cluster(
                architect_name,
                cluster_id,
                indexed,
            )
            if correction is not None:
                applied.append(
                    _correction_row(
                        correction,
                        target_cluster_id=cluster_id,
                    )
                )

    eligible_pairs = len(cluster_ids) * len(stack)
    corrected_pairs = len(applied)
    coverage_pct = (
        round(min(corrected_pairs / eligible_pairs, 1.0) * 100.0, 2)
        if eligible_pairs > 0
        else 0.0
    )

    # Per-architect rollup — every stack architect appears so the UI can
    # render "0/52 clusters calibrated" rather than an empty row.
    by_architect_raw: dict[str, list[dict[str, Any]]] = {
        name: [] for name in stack
    }
    for row in applied:
        by_architect_raw.setdefault(str(row["architect_name"]), []).append(row)

    by_architect: list[dict[str, Any]] = []
    for name in sorted(by_architect_raw):
        rows = by_architect_raw[name]
        scalars = [_safe_float(row["correction_scalar"], 1.0) for row in rows]
        confidence = [
            _safe_float(row["confidence_weight"]) for row in rows
        ]
        samples = [
            _safe_float(row["effective_sample_count"]) for row in rows
        ]
        avg_scalar = (
            round(sum(scalars) / len(scalars), 6) if scalars else 1.0
        )
        max_abs_drift = (
            round(max(abs(scalar - 1.0) for scalar in scalars), 6)
            if scalars
            else 0.0
        )
        by_architect.append(
            {
                "architect_name": name,
                "corrected_clusters": len(rows),
                "total_clusters": len(cluster_ids),
                "coverage_pct": (
                    round(len(rows) / len(cluster_ids) * 100.0, 2)
                    if cluster_ids
                    else 0.0
                ),
                "avg_scalar": avg_scalar,
                "min_scalar": round(min(scalars), 6) if scalars else 1.0,
                "max_scalar": round(max(scalars), 6) if scalars else 1.0,
                "max_abs_drift": max_abs_drift,
                "confidence_avg": (
                    round(sum(confidence) / len(confidence), 6)
                    if confidence
                    else 0.0
                ),
                "sample_sum": round(sum(samples), 4),
                "direction": _direction(scalars),
            }
        )
    by_architect.sort(
        key=lambda row: (-row["max_abs_drift"], row["architect_name"])
    )

    # Per-cluster rollup — every cluster appears with its calibration
    # coverage across the product type's architect stack.
    by_cluster_raw: dict[str, list[dict[str, Any]]] = {
        cluster_id: [] for cluster_id in cluster_ids
    }
    for row in applied:
        by_cluster_raw.setdefault(str(row["cluster_id"]), []).append(row)

    by_cluster: list[dict[str, Any]] = []
    cluster_names = {
        _cluster_id(cluster): _cluster_name(cluster)
        for cluster in cluster_list
    }
    for cluster_id in cluster_ids:
        rows = by_cluster_raw[cluster_id]
        scalars = [_safe_float(row["correction_scalar"], 1.0) for row in rows]
        # "Most corrected" = the row with the largest |scalar - 1| drift;
        # ties break deterministically by architect then cluster id.
        strongest = (
            sorted(
                rows,
                key=lambda row: (
                    -abs(row["correction_scalar"] - 1.0),
                    str(row["architect_name"]),
                    str(row["cluster_id"]),
                ),
            )[0]
            if rows
            else None
        )
        by_cluster.append(
            {
                "cluster_id": cluster_id,
                "cluster_name": cluster_names.get(cluster_id, cluster_id),
                "corrected_architects": len(rows),
                "total_architects": len(stack),
                "coverage_pct": (
                    round(len(rows) / len(stack) * 100.0, 2)
                    if stack
                    else 0.0
                ),
                "avg_scalar": (
                    round(sum(scalars) / len(scalars), 6)
                    if scalars
                    else 1.0
                ),
                "most_corrected_architect": (
                    str(strongest["architect_name"])
                    if strongest is not None
                    else None
                ),
            }
        )
    by_cluster.sort(
        key=lambda row: (
            -row["corrected_architects"],
            -row["avg_scalar"],
            row["cluster_id"],
        )
    )

    strongest = sorted(
        applied,
        key=lambda row: (
            -abs(row["correction_scalar"] - 1.0),
            row["architect_name"],
            row["cluster_id"],
        ),
    )[:limit]

    return {
        "simulation_id": _safe_int(simulation_id),
        "project_id": _safe_int(project_id),
        "product_type": str(product_type or ""),
        "generated_at": (
            generated_at.isoformat()
            if isinstance(generated_at, datetime)
            else datetime.now(UTC).isoformat()
        ),
        "eligible_pairs": eligible_pairs,
        "corrected_pairs": corrected_pairs,
        "coverage_pct": coverage_pct,
        "available_correction_rows": len(indexed),
        "cluster_count": len(cluster_ids),
        "architect_stack_size": len(stack),
        "by_architect": by_architect,
        "by_cluster": by_cluster,
        "corrections": strongest,
        "corrections_returned": len(strongest),
        "corrections_limit": limit,
    }


__all__ = [
    "DEFAULT_CORRECTIONS_LIMIT",
    "DIRECTION_LOWERS",
    "DIRECTION_NEUTRAL",
    "DIRECTION_RAISES",
    "MAX_CORRECTIONS_LIMIT",
    "build_calibration_transparency",
    "coerce_recorded_applied_corrections",
]
