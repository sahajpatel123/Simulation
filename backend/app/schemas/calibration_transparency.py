"""Pydantic schemas for the per-simulation calibration transparency view.

``GET /api/v1/simulations/{simulation_id}/calibration-transparency`` shows
which learned ``architect_corrections`` rows currently apply to the run's
product type, how many (architect, cluster) pairs are covered, and the
strongest adjustments — so founders and operators can see exactly how the
learning layer influences a simulation instead of only a raw counter.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CalibrationCorrectionOut(BaseModel):
    """One effective correction applied to an (architect, cluster) pair."""

    architect_name: str
    cluster_id: str = Field(
        description="The cluster the correction is applied to in this run."
    )
    source_cluster_id: str = Field(
        description=(
            "Cluster scope of the correction row itself — either the same "
            "cluster or ``ALL`` for a global fallback."
        )
    )
    product_type: str = ""
    product_attribute: str = "ALL"
    correction_scalar: float = Field(default=1.0, ge=0.0)
    confidence_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    effective_sample_count: float = Field(default=0.0, ge=0.0)
    scope: str = ""


class ArchitectCalibrationCoverageOut(BaseModel):
    """Per-architect rollup of current learned-correction coverage."""

    architect_name: str
    corrected_clusters: int = Field(default=0, ge=0)
    total_clusters: int = Field(default=0, ge=0)
    coverage_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    avg_scalar: float = Field(default=1.0, ge=0.0)
    min_scalar: float = Field(default=1.0, ge=0.0)
    max_scalar: float = Field(default=1.0, ge=0.0)
    max_abs_drift: float = Field(default=0.0, ge=0.0)
    confidence_avg: float = Field(default=0.0, ge=0.0, le=1.0)
    sample_sum: float = Field(default=0.0, ge=0.0)
    direction: str = "NEUTRAL"


class ClusterCalibrationCoverageOut(BaseModel):
    """Per-cluster rollup of current learned-correction coverage."""

    cluster_id: str
    cluster_name: str = ""
    corrected_architects: int = Field(default=0, ge=0)
    total_architects: int = Field(default=0, ge=0)
    coverage_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    avg_scalar: float = Field(default=1.0, ge=0.0)
    most_corrected_architect: str | None = None


class CalibrationTransparencyOut(BaseModel):
    """Full response for the per-simulation calibration transparency view."""

    simulation_id: int
    project_id: int
    product_type: str = ""
    generated_at: datetime
    eligible_pairs: int = Field(default=0, ge=0)
    corrected_pairs: int = Field(default=0, ge=0)
    coverage_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    available_correction_rows: int = Field(default=0, ge=0)
    cluster_count: int = Field(default=0, ge=0)
    architect_stack_size: int = Field(default=0, ge=0)
    by_architect: list[ArchitectCalibrationCoverageOut] = Field(
        default_factory=list
    )
    by_cluster: list[ClusterCalibrationCoverageOut] = Field(
        default_factory=list
    )
    corrections: list[CalibrationCorrectionOut] = Field(default_factory=list)
    corrections_returned: int = Field(default=0, ge=0)
    corrections_limit: int = Field(default=50, ge=1, le=200)
    recorded_applied_corrections: int | None = Field(
        default=None,
        description=(
            "Correction count persisted in this run's conductor "
            "diagnostics; ``None`` for runs created before that "
            "diagnostic shipped."
        ),
    )


__all__ = [
    "ArchitectCalibrationCoverageOut",
    "CalibrationCorrectionOut",
    "CalibrationTransparencyOut",
    "ClusterCalibrationCoverageOut",
]
