"""
Pydantic schemas for the per-cluster calibration evidence digest
``GET /calibration/cluster-evidence``.

The Layer 5 cluster-trait calibration loop learns from validated founder
outcomes, but the platform had no operator-facing view of *which* clusters
actually carry real-world evidence. This digest surfaces that state per
cluster: validated-outcome count, learning weight, consumed/pending
outcomes, calibrated traits, and a reliability status tier.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ClusterCalibrationEvidence(BaseModel):
    """One consumer cluster's real-world calibration evidence state."""

    cluster_id: str
    cluster_name: str = ""
    population_weight: float = 0.0
    validated_outcomes: int = 0
    learning_weight: float = 0.0
    consumed_outcomes: int = 0
    pending_outcomes: int = 0
    last_processed_outcome_id: int | None = None
    calibration_count: int = 0
    calibrated_traits: list[str] = Field(default_factory=list)
    status: str = "NO_EVIDENCE"  # CALIBRATED / UNDER_EVIDENCED / NO_EVIDENCE


class ClusterCalibrationOverall(BaseModel):
    """Aggregate rollup across all registry clusters."""

    total_clusters: int = 0
    clusters_with_evidence: int = 0
    calibrated_clusters: int = 0
    under_evidenced_clusters: int = 0
    zero_evidence_clusters: int = 0
    total_validated_outcomes: int = 0
    total_consumed_outcomes: int = 0
    total_pending_outcomes: int = 0
    total_trait_updates: int = 0


class ClusterCalibrationDigestOut(BaseModel):
    """Top-level per-cluster calibration evidence digest payload."""

    generated_at: str = ""
    overall: ClusterCalibrationOverall = Field(default_factory=ClusterCalibrationOverall)
    clusters: list[ClusterCalibrationEvidence] = Field(default_factory=list)


__all__ = [
    "ClusterCalibrationEvidence",
    "ClusterCalibrationOverall",
    "ClusterCalibrationDigestOut",
]
