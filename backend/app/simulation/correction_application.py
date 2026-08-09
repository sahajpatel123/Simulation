"""Apply learned architect corrections to simulation outputs.

The calibration engine (``calibration_engine.CalibrationEngine``) writes
learned correction scalars into ``architect_corrections`` after founder
outcomes arrive (weekly systematic-bias and monthly structural-pattern
layers). For those corrections to improve future simulations, the
Conductor loads them once per run and applies the highest-confidence
scalar (cluster-specific or the global ``ALL`` fallback) to each
architect's output metrics before the Markov funnel is built.

Pure / no I/O: the route/task layer supplies the rows fetched from the
DB; all arithmetic here is deterministic and defensively sanitised so
malformed legacy rows can never distort the funnel. Only metric values
that are already probabilities/scores in ``[0.0, 1.0]`` are scaled --
raw quantities such as price ceilings, step counts and other unbounded
metrics pass through untouched so corrections never corrupt
non-conversion values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from app.simulation.architects.base import ArchitectOutput

# Corrections below this confidence are ignored (mirrors the original
# BaseArchitect._apply_correction gate).
MIN_CONFIDENCE_WEIGHT: float = 0.20

# Defense-in-depth bounds for legacy/malformed rows. The calibration
# engine produces scalars near 1.0; anything beyond these bounds would
# distort the funnel, so clamp instead of trusting raw DB values.
MIN_CORRECTION_SCALAR: float = 0.5
MAX_CORRECTION_SCALAR: float = 2.0

# Global cluster sentinel written by the systematic-bias layer.
CLUSTER_ALL: str = "ALL"


@dataclass(frozen=True)
class Correction:
    """One sanitised, ready-to-apply architect correction."""

    architect_name: str
    product_type: str
    product_attribute: str
    cluster_id: str
    correction_scalar: float
    confidence_weight: float
    effective_sample_count: float = 0.0
    scope: str = ""


def _row_value(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Read a key from a mapping-like row (dict or SQLAlchemy RowMapping)."""
    try:
        return row.get(key, default)
    except AttributeError:
        return getattr(row, key, default)


def _sanitise_scalar(raw: Any) -> float | None:
    """Coerce a finite scalar and clamp it to the safe bounds."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return max(MIN_CORRECTION_SCALAR, min(MAX_CORRECTION_SCALAR, value))


def _sanitise_confidence(raw: Any) -> float | None:
    """Coerce a finite confidence weight in ``[0.0, 1.0]``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, value))


def _safe_sample_count(raw: Any) -> float:
    if raw is None or isinstance(raw, bool):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value > 0.0 else 0.0


def _is_better(candidate: Correction, current: Correction) -> bool:
    """Deterministic ordering: confidence, then cluster specificity, then
    sample size. This mirrors the original query's confidence-only ORDER BY
    while making ties reproducible."""
    if candidate.confidence_weight != current.confidence_weight:
        return candidate.confidence_weight > current.confidence_weight
    candidate_cluster_specific = candidate.cluster_id != CLUSTER_ALL
    current_cluster_specific = current.cluster_id != CLUSTER_ALL
    if candidate_cluster_specific != current_cluster_specific:
        return candidate_cluster_specific
    return (
        candidate.effective_sample_count
        > current.effective_sample_count
    )


def index_corrections(
    rows: Sequence[Mapping[str, Any]] | None,
    product_type: str,
) -> dict[tuple[str, str], Correction]:
    """Return the best applicable correction per ``(architect, cluster)``.

    Only rows for ``product_type`` with confidence at least
    :data:`MIN_CONFIDENCE_WEIGHT` are considered. For each architect +
    cluster pair the highest-confidence row wins; ties prefer the
    cluster-specific row, then the larger effective sample count.
    """
    best: dict[tuple[str, str], Correction] = {}
    for raw in rows or []:
        architect = _row_value(raw, "architect_name")
        product_type_row = _row_value(raw, "product_type")
        cluster_id = _row_value(raw, "cluster_id")
        if not architect or not cluster_id or str(product_type_row) != product_type:
            continue
        confidence = _sanitise_confidence(_row_value(raw, "confidence_weight"))
        if confidence is None or confidence < MIN_CONFIDENCE_WEIGHT:
            continue
        scalar = _sanitise_scalar(_row_value(raw, "correction_scalar"))
        if scalar is None:
            continue
        candidate = Correction(
            architect_name=str(architect),
            product_type=str(product_type_row),
            product_attribute=str(_row_value(raw, "product_attribute") or CLUSTER_ALL),
            cluster_id=str(cluster_id),
            correction_scalar=scalar,
            confidence_weight=confidence,
            effective_sample_count=_safe_sample_count(
                _row_value(raw, "effective_sample_count")
            ),
            scope=str(_row_value(raw, "scope") or ""),
        )
        key = (candidate.architect_name, candidate.cluster_id)
        current = best.get(key)
        if current is None or _is_better(candidate, current):
            best[key] = candidate
    return best


def correction_for_output(
    output: ArchitectOutput,
    corrections: Mapping[tuple[str, str], Correction] | None,
) -> Correction | None:
    """Return the correction matching an output, if any.

    A cluster-specific row wins over the global ``ALL`` row on a
    confidence tie; otherwise the higher-confidence row wins (mirroring
    the original ``BaseArchitect._apply_correction`` SQL semantics).
    """
    if not corrections:
        return None
    exact = corrections.get((output.architect_name, output.cluster_id))
    global_row = corrections.get((output.architect_name, CLUSTER_ALL))
    if exact is None:
        return global_row
    if global_row is None:
        return exact
    if global_row.confidence_weight > exact.confidence_weight:
        return global_row
    return exact


def _scale_metric(value: Any, scalar: float) -> Any:
    """Scale only probability/score floats in ``[0.0, 1.0]``."""
    if not isinstance(value, float):
        return value
    if value < 0.0 or value > 1.0:
        return value
    return max(0.0, min(1.0, value * scalar))


def apply_correction_to_output(
    output: ArchitectOutput,
    corrections: Mapping[tuple[str, str], Correction] | None,
) -> ArchitectOutput:
    """Return a copy of ``output`` with calibrated metrics applied.

    Returns the same object when no correction matches or when no metric
    is eligible, so callers can detect whether anything changed via an
    identity check.
    """
    correction = correction_for_output(output, corrections)
    if correction is None:
        return output
    scaled = {
        key: _scale_metric(value, correction.correction_scalar)
        for key, value in output.metrics.items()
    }
    if all(scaled[key] == value for key, value in output.metrics.items()):
        return output
    return replace(output, metrics=scaled)


__all__ = [
    "CLUSTER_ALL",
    "MAX_CORRECTION_SCALAR",
    "MIN_CONFIDENCE_WEIGHT",
    "MIN_CORRECTION_SCALAR",
    "Correction",
    "apply_correction_to_output",
    "correction_for_output",
    "index_corrections",
]
