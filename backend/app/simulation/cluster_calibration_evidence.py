"""
Pure builder for the per-cluster calibration evidence digest.

The Layer 5 cluster-trait calibration loop
(``CalibrationEngine.update_cluster_trait_calibration``) learns from
validated founder outcomes, but the platform had no operator-facing view of
*which* consumer clusters actually carry real-world evidence. This builder
closes that gap: for every registry cluster it reports the validated-outcome
count, learning weight, how many outcomes Layer 5 has consumed, how many are
still pending, which traits have been calibrated, and a reliability status
tier — so the platform can show "where the model is safe to trust" instead of
hiding evidence gaps inside SQL.

The builder is pure-Python (no DB, no I/O) so it is verifiable with plain
dicts and any cluster-like objects exposing ``cluster_id``, ``name`` and
``population_weight``.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Mapping

from app.simulation.calibration_engine import CLUSTER_TRAIT_CALIBRATION_MIN_EFF_COUNT

# Status tiers shared with the Pydantic schema.
CALIBRATED: str = "CALIBRATED"
UNDER_EVIDENCED: str = "UNDER_EVIDENCED"
NO_EVIDENCE: str = "NO_EVIDENCE"
VALID_STATUSES: frozenset[str] = frozenset({CALIBRATED, UNDER_EVIDENCED, NO_EVIDENCE})


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce to a finite non-negative float or return ``default``.

    Both numeric fields this module reads (``learning_weight`` and
    ``population_weight``) are non-negative by construction, so a negative
    or NaN value is treated as malformed rather than trusted.
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed) if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to a non-negative int or return ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else 0


def _normalise_evidence(evidence_rows: list[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Group evidence rows by cluster id with guarded numeric fields.

    ``consumed_outcomes`` / ``pending_outcomes`` may be absent in a
    malformed row; ``None`` is preserved so the caller can recompute one
    from the other instead of silently trusting a broken count.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in evidence_rows or []:
        if not isinstance(row, Mapping):
            continue
        cluster_id = row.get("cluster_id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            continue
        validated = _safe_int(row.get("validated_outcomes"))
        weight = _safe_float(row.get("learning_weight"))
        consumed_raw = row.get("consumed_outcomes")
        pending_raw = row.get("pending_outcomes")
        last_raw = row.get("last_processed_outcome_id")
        # The digest only counts learning-weighted evidence (the SQL filters
        # ``learning_weight > 0``), so a row with a non-positive weight is
        # malformed even if it carries a numeric outcome count.
        if weight <= 0.0:
            validated = 0
            consumed_raw = 0
            pending_raw = 0
            last_raw = None
        out[cluster_id.strip()] = {
            "validated_outcomes": validated,
            "learning_weight": weight,
            "consumed_outcomes": None if consumed_raw is None else _safe_int(consumed_raw),
            "pending_outcomes": None if pending_raw is None else _safe_int(pending_raw),
            "last_processed_outcome_id": (
                None if last_raw is None else _safe_int(last_raw)
            ),
        }
    return out


def _normalise_traits(trait_rows: list[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Aggregate ``cluster_parameters`` calibration rows per cluster.

    Only rows with a positive ``calibration_count`` contribute. Trait names
    are de-duplicated and sorted so the payload is deterministic.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in trait_rows or []:
        if not isinstance(row, Mapping):
            continue
        cluster_id = row.get("cluster_id")
        trait_name = row.get("trait_name")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            continue
        if not isinstance(trait_name, str) or not trait_name.strip():
            continue
        count = _safe_int(row.get("calibration_count"))
        if count <= 0:
            continue
        bucket = out.setdefault(
            cluster_id.strip(),
            {"count": 0, "traits": set()},
        )
        bucket["count"] += count
        bucket["traits"].add(trait_name.strip())
    return {
        cid: {"count": bucket["count"], "traits": sorted(bucket["traits"])}
        for cid, bucket in out.items()
    }


def _status(learning_weight: float) -> str:
    if learning_weight >= CLUSTER_TRAIT_CALIBRATION_MIN_EFF_COUNT:
        return CALIBRATED
    if learning_weight > 0.0:
        return UNDER_EVIDENCED
    return NO_EVIDENCE


def build_cluster_calibration_digest(
    evidence_rows: list[Mapping[str, Any]] | None = None,
    trait_rows: list[Mapping[str, Any]] | None = None,
    clusters: list[Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the per-cluster calibration evidence digest.

    Args:
        evidence_rows: Validated founder-outcome aggregates per cluster
            (``cluster_id``, ``validated_outcomes``, ``learning_weight``,
            ``consumed_outcomes``, ``pending_outcomes``,
            ``last_processed_outcome_id``).
        trait_rows: ``cluster_parameters`` rows with ``calibration_count``
            > 0 (``cluster_id``, ``trait_name``, ``calibration_count``).
        clusters: Canonical cluster definitions (defaults to empty).
        generated_at: ISO timestamp echoed back; defaults to now.

    Returns:
        Dict matching the ``ClusterCalibrationDigestOut`` schema with
        ``generated_at``, ``overall`` and an evidence-ranked ``clusters``
        list. Unknown evidence cluster ids (not in the registry) are still
        surfaced with blank names so stale DB rows can't vanish silently.
    """
    evidence = _normalise_evidence(evidence_rows)
    traits = _normalise_traits(trait_rows)

    known: dict[str, Any] = {}
    for defn in clusters or []:
        cluster_id = getattr(defn, "cluster_id", None)
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            continue
        known[cluster_id.strip()] = defn

    cluster_rows: list[dict[str, Any]] = []
    for cluster_id in sorted(set(known) | set(evidence)):
        ev = evidence.get(cluster_id, {})
        validated = int(ev.get("validated_outcomes", 0))
        weight = round(float(ev.get("learning_weight", 0.0)), 4)
        consumed_raw = ev.get("consumed_outcomes")
        pending_raw = ev.get("pending_outcomes")
        if consumed_raw is None and pending_raw is None:
            consumed = 0
            pending = validated
        elif consumed_raw is None:
            consumed = max(0, validated - int(pending_raw))
            pending = int(pending_raw)
        else:
            consumed = int(consumed_raw)
            pending = max(0, validated - consumed) if pending_raw is None else int(pending_raw)

        defn = known.get(cluster_id)
        trait_bucket = traits.get(cluster_id, {"count": 0, "traits": []})
        cluster_rows.append(
            {
                "cluster_id": cluster_id,
                "cluster_name": getattr(defn, "name", "") or "",
                "population_weight": round(
                    _safe_float(getattr(defn, "population_weight", 0.0)), 4
                ),
                "validated_outcomes": validated,
                "learning_weight": weight,
                "consumed_outcomes": consumed,
                "pending_outcomes": pending,
                "last_processed_outcome_id": ev.get("last_processed_outcome_id"),
                "calibration_count": int(trait_bucket["count"]),
                "calibrated_traits": list(trait_bucket["traits"]),
                "status": _status(weight),
            }
        )

    # Evidence-ranked, then alphabetically stable: the clusters with the
    # most real-world feedback come first, zero-evidence clusters last.
    cluster_rows.sort(key=lambda row: (-row["learning_weight"], row["cluster_id"]))

    overall = {
        "total_clusters": len(known),
        "clusters_with_evidence": sum(
            1 for row in cluster_rows if row["validated_outcomes"] > 0
        ),
        "calibrated_clusters": sum(1 for row in cluster_rows if row["status"] == CALIBRATED),
        "under_evidenced_clusters": sum(
            1 for row in cluster_rows if row["status"] == UNDER_EVIDENCED
        ),
        "zero_evidence_clusters": sum(
            1 for row in cluster_rows if row["status"] == NO_EVIDENCE
        ),
        "total_validated_outcomes": sum(
            row["validated_outcomes"] for row in cluster_rows
        ),
        "total_consumed_outcomes": sum(row["consumed_outcomes"] for row in cluster_rows),
        "total_pending_outcomes": sum(row["pending_outcomes"] for row in cluster_rows),
        "total_trait_updates": sum(row["calibration_count"] for row in cluster_rows),
    }

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "overall": overall,
        "clusters": cluster_rows,
    }


__all__ = [
    "CALIBRATED",
    "UNDER_EVIDENCED",
    "NO_EVIDENCE",
    "VALID_STATUSES",
    "build_cluster_calibration_digest",
]
