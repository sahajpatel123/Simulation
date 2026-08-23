"""
Pydantic schemas for the evidence-quality endpoint
``GET /api/v1/projects/{project_id}/evidence-quality``.

The evidence-verdicts scorecard reports what each record *says*; this
endpoint grades how much each record deserves to be *trusted*. Every
logged experiment gets a deterministic 0..1 quality score combining
method reliability (a paid acquisition test outranks desk research),
decisiveness (PASS/FAIL vs INCONCLUSIVE), whether an observed metric was
recorded at all, and recency. Assumption-level and project-level indices
roll those up, and the weakest link is called out.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

QUALITY_LABEL_LITERAL = Literal["HIGH", "MEDIUM", "LOW"]


class EvidenceQualityRow(BaseModel):
    """One assumption's evidence quality rollup."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    evidence_count: int = Field(default=0, ge=0)
    latest_method: str | None = None
    latest_method_reliability: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Evidential weight of the latest row's method.",
    )
    latest_result: str | None = None
    latest_age_days: int | None = Field(default=None, ge=0)
    quality: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_label: QUALITY_LABEL_LITERAL = "LOW"
    reasons: list[str] = Field(
        default_factory=list,
        description="Why the quality was graded down, most limiting first.",
    )


class WeakestLinkOut(BaseModel):
    """The tested assumption whose evidence deserves least trust."""

    assumption_id: int
    assumption_text: str = ""
    quality: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_label: QUALITY_LABEL_LITERAL = "LOW"
    reason: str = ""


class EvidenceQualityOut(BaseModel):
    """Full response for the evidence-quality endpoint."""

    project_id: int
    total_assumptions: int = Field(default=0, ge=0)
    tested_count: int = Field(default=0, ge=0)
    untested_count: int = Field(default=0, ge=0)
    high_count: int = Field(default=0, ge=0)
    medium_count: int = Field(default=0, ge=0)
    low_count: int = Field(default=0, ge=0)
    evidence_quality_index: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Mean assumption quality across tested assumptions; "
        "None when nothing has been logged yet.",
    )
    index_label: QUALITY_LABEL_LITERAL | None = None
    weakest_link: WeakestLinkOut | None = None
    rows: list[EvidenceQualityRow] = Field(
        default_factory=list,
        description="Lowest-quality tested assumptions first.",
    )
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "QUALITY_LABEL_LITERAL",
    "EvidenceQualityOut",
    "EvidenceQualityRow",
    "WeakestLinkOut",
]
