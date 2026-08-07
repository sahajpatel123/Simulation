"""Pydantic schemas for the per-project funnel calibration digest."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FunnelStageCalibration(BaseModel):
    """Per-stage simulated-vs-actual drop-off calibration."""

    stage: str
    predicted_drop_off_rate: float | None = None
    actual_drop_off_rate: float | None = None
    sample_count: int = 0
    mean_abs_gap: float | None = None
    bias: float | None = None
    direction: str = "INSUFFICIENT_DATA"
    severity: str = "watch"
    primary_domain: str = ""
    recommended_architects: list[str] = Field(default_factory=list)


class FunnelPrimaryMismatch(BaseModel):
    """The single stage with the largest |predicted − actual| gap."""

    stage: str
    domain: str
    mean_abs_gap: float
    direction: str
    recommended_architects: list[str] = Field(default_factory=list)


class FunnelBiasSummary(BaseModel):
    """Overall simulated-vs-actual funnel drop-off bias."""

    direction: str = "INSUFFICIENT_DATA"
    bias: float | None = None


class FunnelCalibrationDigestOut(BaseModel):
    """Response from ``GET /projects/{id}/funnel-calibration-digest``.

    Tells a founder *which* forward funnel stage the simulation is
    mis-predicting relative to real-world outcomes, how big the gap is,
    and which domain the dashboard should investigate.
    """

    outcome_count: int = 0
    usable_count: int = 0
    stages: list[FunnelStageCalibration] = Field(default_factory=list)
    primary_mismatch_stage: str | None = None
    primary_mismatch: FunnelPrimaryMismatch | None = None
    funnel_bias: FunnelBiasSummary = Field(default_factory=FunnelBiasSummary)
    narrative: str = ""
    key_signals: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "FunnelStageCalibration",
    "FunnelPrimaryMismatch",
    "FunnelBiasSummary",
    "FunnelCalibrationDigestOut",
]
