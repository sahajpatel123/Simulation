"""Pydantic schemas for the evidence-freshness endpoint.

``GET /projects/{project_id}/evidence-freshness`` answers the staleness
question the digest and momentum payloads leave open: how old is each
assumption's latest evidence, and what should be re-tested first? Like the
other validation endpoints it is simulation-independent — usable from the
first logged experiment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.simulation.evidence_staleness import (
    DEFAULT_AGING_DAYS,
    DEFAULT_FRESH_DAYS,
    FRESHNESS_AGING,
    FRESHNESS_FRESH,
    FRESHNESS_NEVER_TESTED,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
)


class EvidenceStalenessRowOut(BaseModel):
    """Freshness verdict for one assumption."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    sensitivity: str = "MEDIUM"
    evidence_count: int = Field(default=0, ge=0)
    last_evidence_at: datetime | None = None
    days_since_last_evidence: float | None = Field(default=None, ge=0.0)
    freshness: Literal[
        "FRESH", "AGING", "STALE", "NEVER_TESTED", "UNKNOWN"
    ] = FRESHNESS_NEVER_TESTED


class EvidenceStalenessSummaryOut(BaseModel):
    """Project-level freshness rollup.

    ``actionable_count`` (stale + never-tested) is the length of the
    founder's re-test queue; ``fresh_share_of_tested_pct`` is the fraction
    of tested-and-dated assumptions still inside the fresh window.
    """

    total_assumptions: int = Field(default=0, ge=0)
    tested_assumptions: int = Field(default=0, ge=0)
    fresh_count: int = Field(default=0, ge=0)
    aging_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    never_tested_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    actionable_count: int = Field(default=0, ge=0)
    fresh_share_of_tested_pct: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    stale_share_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    oldest_days_since_evidence: float | None = Field(default=None, ge=0.0)


class EvidenceStalenessMetaOut(BaseModel):
    """Provenance for one freshness computation."""

    generated_at: datetime | None = None
    model: str = "evidence_staleness_v1"
    fresh_days: int = Field(default=DEFAULT_FRESH_DAYS, ge=1)
    aging_days: int = Field(default=DEFAULT_AGING_DAYS, ge=2)


# Re-exported so API consumers can branch on the canonical labels.
FRESHNESS_VALUES: tuple[str, ...] = (
    FRESHNESS_FRESH,
    FRESHNESS_AGING,
    FRESHNESS_STALE,
    FRESHNESS_NEVER_TESTED,
    FRESHNESS_UNKNOWN,
)


class EvidenceStalenessOut(BaseModel):
    """Full payload for ``GET /projects/{id}/evidence-freshness``."""

    project_id: int
    summary: EvidenceStalenessSummaryOut
    rows: list[EvidenceStalenessRowOut] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    meta: EvidenceStalenessMetaOut
