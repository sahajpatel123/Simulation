"""
Pydantic schemas for the A/B landing-page experiment analysis endpoint
``POST /api/v1/experiments/ab-analysis``.

The endpoint takes two observed arms (``visitors`` / ``conversions``) and
returns a statistical verdict — significance, uplift, confidence interval,
and sample-size guidance — so a founder can tell whether a real-world
landing-page test is worth shipping or still needs traffic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.simulation.ab_test_analysis import VERDICT_INSUFFICIENT_DATA


class AbTestVariantIn(BaseModel):
    """One observed test arm."""

    model_config = {"extra": "forbid"}

    label: str = Field(
        default="",
        max_length=80,
        description="Human-readable arm name (defaults to Control/Variant).",
    )
    visitors: int = Field(
        ge=1,
        description="Unique visitors / sessions observed on this arm.",
    )
    conversions: int = Field(
        ge=0,
        description="Conversions (purchases, signups, etc.) on this arm.",
    )

    @model_validator(mode="after")
    def _conversions_within_visitors(self) -> AbTestVariantIn:
        if self.conversions > self.visitors:
            raise ValueError(
                "conversions cannot exceed visitors on the same arm"
            )
        return self


class AbTestAnalysisIn(BaseModel):
    """Request body for the A/B analysis endpoint."""

    model_config = {"extra": "forbid"}

    variant_a: AbTestVariantIn = Field(
        description="Control arm (first observed variant)."
    )
    variant_b: AbTestVariantIn = Field(
        description="Challenger arm (second observed variant)."
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        allow_inf_nan=False,
        description="Significance level used for the verdict.",
    )
    power: float = Field(
        default=0.80,
        gt=0.0,
        lt=1.0,
        allow_inf_nan=False,
        description="Statistical power used for sample-size guidance.",
    )
    minimum_detectable_effect: float = Field(
        default=0.02,
        gt=0.0,
        le=0.5,
        allow_inf_nan=False,
        description=(
            "Minimum absolute conversion uplift to size the test for when "
            "the observed uplift is too small to power a recommendation."
        ),
    )


class AbTestVariantOut(BaseModel):
    """Normalised output for one test arm."""

    label: str
    visitors: int
    conversions: int
    conversion_rate: float


class AbTestAnalysisOut(BaseModel):
    """Statistical verdict for two observed A/B arms."""

    variant_a: AbTestVariantOut
    variant_b: AbTestVariantOut
    winner: str | None = Field(
        description="Label of the arm with the higher observed rate, if any."
    )
    pooled_conversion_rate: float = 0.0
    absolute_uplift: float = 0.0
    relative_uplift_pct: float | None = None
    z_score: float | None = None
    p_value: float | None = None
    confidence_interval: dict[str, float | None] = Field(
        default_factory=lambda: {"low": None, "high": None}
    )
    verdict: str = VERDICT_INSUFFICIENT_DATA
    significant: bool = False
    confidence_level: float = 0.95
    visitors_needed_for_observed_uplift: int | None = None
    visitors_needed_for_mde: int | None = None
    narrative: str = ""
    recommendations: list[str] = Field(default_factory=list)
    key_signals: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class AbTestExperimentCreate(BaseModel):
    """Create a persisted A/B experiment for a project."""

    model_config = {"extra": "forbid"}

    name: str = Field(
        min_length=1,
        max_length=120,
        description="Short founder-facing name for the test.",
    )
    hypothesis: str | None = Field(
        default=None,
        max_length=2000,
        description="What the founder expected to change and why.",
    )
    analysis: AbTestAnalysisIn = Field(
        description="Observed arms and statistical parameters to log."
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped


class AbTestExperimentUpdate(BaseModel):
    """Partial update for a persisted A/B experiment."""

    model_config = {"extra": "forbid"}

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="New founder-facing name for the test.",
    )
    hypothesis: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "New hypothesis; pass null to clear an existing one."
        ),
    )
    analysis: AbTestAnalysisIn | None = Field(
        default=None,
        description=(
            "Replacement observed arms / statistical parameters; "
            "recomputes the verdict snapshot."
        ),
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped

    @model_validator(mode="after")
    def _at_least_one_field(self) -> AbTestExperimentUpdate:
        if not self.model_fields_set:
            raise ValueError(
                "provide at least one of name, hypothesis, analysis"
            )
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class AbTestExperimentOut(BaseModel):
    """A persisted A/B experiment with its stored statistical verdict."""

    id: int
    project_id: int
    name: str
    hypothesis: str | None
    analysis: AbTestAnalysisOut
    verdict: str
    significant: bool
    winner: str | None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "AbTestAnalysisIn",
    "AbTestAnalysisOut",
    "AbTestExperimentCreate",
    "AbTestExperimentOut",
    "AbTestExperimentUpdate",
    "AbTestVariantIn",
    "AbTestVariantOut",
]
