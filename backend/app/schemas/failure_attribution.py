"""Pydantic schemas for the post-launch failure-attribution digest.

``GET /api/v1/projects/{id}/failure-attribution`` groups a project's
recorded founder outcomes by the ``primary_failure_reason`` the founder
submitted at outcome-feedback time, then pairs each reason with the
model's prediction error so the dashboard can answer "what failed, and
how badly did the simulation miss when that reason was reported?".

The digest intentionally stays read-only and advisory: attribution is
self-reported founder data, so every number is labeled with how many
outcomes it is based on.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FailureAttributionReason(BaseModel):
    """One grouped failure reason with its prediction-error rollup."""

    reason: str = Field(min_length=1, max_length=50)
    count: int = Field(ge=1)
    share_pct: float = Field(ge=0.0, le=100.0)
    avg_abs_variance_pp: float | None = Field(default=None, ge=0.0)
    avg_signed_variance_pp: float | None = Field(default=None)
    avg_signal_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_learning_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_days_since_launch: float | None = Field(default=None, ge=0.0)
    data_confidence_breakdown: dict[str, int] = Field(default_factory=dict)
    product_changed_count: int = Field(default=0, ge=0)
    pricing_changed_count: int = Field(default=0, ge=0)
    target_market_changed_count: int = Field(default=0, ge=0)
    severity: str = "watch"


class FailureAttributionOut(BaseModel):
    """Full post-launch failure-attribution payload for one project."""

    project_id: int
    total_outcomes: int = Field(default=0, ge=0)
    attributed_count: int = Field(default=0, ge=0)
    unattributed_count: int = Field(default=0, ge=0)
    top_reason: str | None = Field(default=None, max_length=50)
    reasons: list[FailureAttributionReason] = Field(default_factory=list)
    narrative: str = ""
    key_signals: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "FailureAttributionReason",
    "FailureAttributionOut",
]
