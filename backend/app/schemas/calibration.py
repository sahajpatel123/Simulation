"""
Pydantic schemas for the calibration-status diagnostics view
``GET /analytics/calibration/status``.

The calibration engine runs across 5 layers (validate_outcome,
update_systematic_bias, update_structural_patterns,
update_user_accuracy_profile, update_cluster_trait_calibration). This
view surfaces the *current state* of those layers in a single dashboard.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OutcomeCoverage(BaseModel):
    """Counts of founder outcomes by validation state."""

    total: int = 0
    validated: int = 0
    rejected: int = 0
    pending: int = 0  # not yet processed by validate_outcome
    validation_rate_pct: float = 0.0


class ArchitectCorrection(BaseModel):
    """A single correction row from the architect_corrections table."""

    architect_name: str
    product_type: str = "ALL"
    product_attribute: str = "ALL"
    cluster_id: str = "ALL"
    correction_scalar: float
    confidence_weight: float
    effective_sample_count: float = 0.0
    scope: str = "CATEGORY_GLOBAL"
    last_updated: str | None = None


class ArchitectHealth(BaseModel):
    """Per-architect calibration health summary."""

    architect_name: str
    correction_count: int = 0
    avg_scalar: float = 1.0
    max_abs_drift: float = 0.0
    confidence_avg: float = 0.0
    effective_sample_count: float = 0.0
    is_calibrated: bool = False  # True when effective_sample_count >= 10

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ArchitectWeightedDrift(BaseModel):
    """Per-architect confidence-weighted bias summary."""

    architect_name: str
    weighted_drift: float = 0.0
    confidence_sum: float = 0.0
    sample_sum: float = 0.0
    direction: str = "STABLE"  # one of BIASED_UP / BIASED_DOWN / STABLE


class WeightedDriftSummary(BaseModel):
    """Aggregate rollup of confidence-weighted bias across architects."""

    total_architects: int = 0
    biased_up_count: int = 0
    biased_down_count: int = 0
    stable_count: int = 0
    by_architect: list[ArchitectWeightedDrift] = Field(default_factory=list)


class CalibrationStatusOut(BaseModel):
    """Top-level calibration status payload."""

    outcome_coverage: OutcomeCoverage = Field(default_factory=OutcomeCoverage)
    total_correction_rows: int = 0
    by_architect: list[ArchitectHealth] = Field(default_factory=list)
    by_product_type: dict[str, int] = Field(default_factory=dict)
    calibrated_architects: int = 0
    under_calibrated_architects: int = 0
    under_calibrated_list: list[str] = Field(default_factory=list)
    weighted_drift: WeightedDriftSummary = Field(default_factory=WeightedDriftSummary)
    generated_at: str = ""


__all__ = [
    "OutcomeCoverage",
    "ArchitectCorrection",
    "ArchitectHealth",
    "ArchitectWeightedDrift",
    "WeightedDriftSummary",
    "CalibrationStatusOut",
]
