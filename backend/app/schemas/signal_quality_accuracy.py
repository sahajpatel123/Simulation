"""Schemas for ``GET /calibration/my-signal-quality-accuracy``.

The digest checks whether simulations built from stronger evidence actually
produce smaller real-world conversion errors for the current user.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SignalQualityTier = Literal["QUARANTINED", "PARTIAL", "FULL"]
SignalQualityAccuracyVerdict = Literal[
    "QUALITY_ALIGNED",
    "QUALITY_INVERTED",
    "FLAT",
    "INSUFFICIENT_DATA",
]


class SignalQualityAccuracyBucket(BaseModel):
    """Prediction-error metrics for one canonical signal-quality tier."""

    tier: SignalQualityTier
    minimum_signal_quality: float = Field(ge=0.0, le=1.0)
    maximum_signal_quality: float = Field(ge=0.0, le=1.0)
    outcome_count: int = Field(default=0, ge=0)
    mean_absolute_error: float | None = Field(default=None, ge=0.0, le=1.0)
    root_mean_square_error: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_signed_error: float | None = Field(default=None, ge=-1.0, le=1.0)
    overprediction_count: int = Field(default=0, ge=0)
    underprediction_count: int = Field(default=0, ge=0)
    exact_count: int = Field(default=0, ge=0)


class SignalQualityAccuracyOut(BaseModel):
    """How prediction error changes as the user's input quality improves."""

    user_id: int
    generated_at: str = ""
    total_outcomes: int = Field(default=0, ge=0)
    discarded_rows: int = Field(default=0, ge=0)
    populated_tier_count: int = Field(default=0, ge=0, le=3)
    verdict: SignalQualityAccuracyVerdict = "INSUFFICIENT_DATA"
    comparison_from_tier: SignalQualityTier | None = None
    comparison_to_tier: SignalQualityTier | None = None
    absolute_error_improvement: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description=(
            "Lower-quality MAE minus higher-quality MAE; positive means "
            "accuracy improved as signal quality rose."
        ),
    )
    relative_error_reduction: float | None = None
    buckets: list[SignalQualityAccuracyBucket] = Field(default_factory=list)
    narrative: str = ""
    recommendations: list[str] = Field(default_factory=list)


__all__ = [
    "SignalQualityTier",
    "SignalQualityAccuracyVerdict",
    "SignalQualityAccuracyBucket",
    "SignalQualityAccuracyOut",
]
