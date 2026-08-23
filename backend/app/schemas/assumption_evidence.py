"""
Pydantic schemas for the assumption-evidence log and de-risking scorecard.

The validation-experiment planner tells a founder *what to run*; these
schema/models let the founder record *what happened* (PASS / FAIL /
INCONCLUSIVE) and see how that evidence upgrades or challenges the
assumption's confidence — and how the validation-ROI ranking shifts as a
result.

Endpoints:
* ``POST /projects/{project_id}/assumptions/{assumption_id}/evidence``
* ``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard``
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.validation_experiment import METHOD_ID_LITERAL
from app.schemas.validation_roi import CONFIDENCE_TIER_LITERAL, ROI_TIER_LITERAL

EVIDENCE_RESULT_LITERAL = Literal["PASS", "FAIL", "INCONCLUSIVE"]


class EvidenceCreate(BaseModel):
    """Body for logging one validation experiment result."""

    model_config = {"extra": "forbid"}

    method: METHOD_ID_LITERAL
    result: EVIDENCE_RESULT_LITERAL
    observed_metric: float | None = Field(default=None, ge=0.0)
    notes: str | None = Field(default=None, max_length=500)


EVIDENCE_IMPORT_MAX_ROWS: int = 200


class EvidenceImportRow(BaseModel):
    """One experiment result inside a bulk evidence import.

    A row names its assumption either by ``assumption_id`` or by
    ``assumption_text`` (case-insensitive match against the project's
    assumptions) — the text path lets founders paste evidence straight
    from an assumptions export without looking up internal IDs.
    """

    model_config = {"extra": "forbid"}

    assumption_id: int = Field(default=0, ge=0)
    assumption_text: str | None = Field(default=None, max_length=2000)
    method: METHOD_ID_LITERAL
    result: EVIDENCE_RESULT_LITERAL
    observed_metric: float | None = Field(default=None, ge=0.0)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _require_id_or_text(self) -> EvidenceImportRow:
        if self.assumption_id <= 0 and not (
            self.assumption_text or ""
        ).strip():
            raise ValueError(
                "provide either assumption_id or assumption_text"
            )
        return self


class EvidenceImportRequest(BaseModel):
    """Body for bulk-logging validation experiment results."""

    model_config = {"extra": "forbid"}

    rows: list[EvidenceImportRow] = Field(
        min_length=1,
        max_length=EVIDENCE_IMPORT_MAX_ROWS,
    )


class EvidenceImportSkippedRow(BaseModel):
    """One rejected import row, with why it was rejected."""

    index: int = Field(ge=0)
    assumption_id: int | None = None
    reason: str


class EvidenceImportOut(BaseModel):
    """Result summary of a bulk evidence import.

    Valid rows are inserted atomically; invalid rows never block valid
    ones — each is reported in ``skipped_rows`` with a founder-readable
    reason so a spreadsheet paste can be corrected and re-run.
    """

    project_id: int
    imported_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    skipped_rows: list[EvidenceImportSkippedRow] = Field(default_factory=list)
    assumption_ids_touched: list[int] = Field(default_factory=list)


class EvidenceOut(BaseModel):
    """One recorded experiment, with the confidence tier it implies."""

    id: int
    project_id: int
    assumption_id: int
    assumption_text: str = ""
    # Plain str on output: input is enum-constrained, but a legacy DB row
    # must never break response serialisation.
    method: str = ""
    method_label: str = ""
    result: str = ""
    observed_metric: float | None = None
    notes: str | None = None
    created_at: datetime | None = None
    derived_confidence: CONFIDENCE_TIER_LITERAL | None = None


class AssumptionEvidenceScorecardOut(BaseModel):
    """Per-assumption de-risking scorecard: evidence history + ROI shift."""

    project_id: int
    assumption_id: int
    assumption_text: str = ""
    category: str = ""
    sensitivity: str = ""
    evidence_count: int = Field(default=0, ge=0)
    latest_result: str | None = None
    derived_confidence: CONFIDENCE_TIER_LITERAL | None = Field(
        default=None,
        description=(
            "Confidence tier implied by the most recent decisive experiment "
            "(PASS/FAIL), before the 'never downgrade stronger evidence' rule "
            "is applied."
        ),
    )
    confidence_before: CONFIDENCE_TIER_LITERAL = "DESIGN_INTENT"
    confidence_after: CONFIDENCE_TIER_LITERAL | None = Field(
        default=None,
        description=(
            "Effective confidence tier after the evidence rule — the tier the "
            "validation-ROI recomputation actually uses."
        ),
    )
    validation_roi_before: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_roi_after: float | None = Field(default=None, ge=0.0, le=1.0)
    roi_tier_before: ROI_TIER_LITERAL | None = None
    roi_tier_after: ROI_TIER_LITERAL | None = None
    roi_delta: float = 0.0
    tier_upgraded: bool = Field(
        default=False,
        description=(
            "True when the validation-ROI tier changed as a result of the "
            "evidence. Direction matters: a FAIL can push priority up, a PASS "
            "can drop it — compare roi_tier_before/roi_tier_after."
        ),
    )
    recommendation: str = ""
    history: list[EvidenceOut] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class AssumptionEvidenceDigestAssumption(BaseModel):
    """One assumption row in the project-level evidence digest."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    sensitivity: str = "MEDIUM"
    evidence_count: int = Field(default=0, ge=0)
    latest_result: str | None = None
    derived_confidence: CONFIDENCE_TIER_LITERAL | None = None
    # DE_RISKED | CHALLENGED | INCONCLUSIVE | PENDING
    status: str = "PENDING"


class AssumptionEvidenceDigestOut(BaseModel):
    """Project-level rollup of every logged validation experiment.

    The per-assumption scorecard answers "did this claim get tested?"; this
    digest answers "how much of the project's risk has actually been
    validated?" — coverage, de-risked vs challenged vs pending counts,
    result/method histograms, and the next highest-leverage experiments to
    run. It is deliberately simulation-independent: a founder can see
    evidence progress even before the first simulation completes.
    """

    project_id: int
    total_assumptions: int = Field(default=0, ge=0)
    total_evidence_rows: int = Field(default=0, ge=0)
    assumptions_with_evidence: int = Field(default=0, ge=0)
    evidence_coverage_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    de_risked_count: int = Field(default=0, ge=0)
    challenged_count: int = Field(default=0, ge=0)
    inconclusive_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    validation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    result_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Histogram of logged results: PASS/FAIL/INCONCLUSIVE, plus OTHER "
            "for unrecognised legacy result values."
        ),
    )
    method_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Histogram of experiment methods; known methods are canonicalised "
            "to their schema spelling."
        ),
    )
    top_pending: list[AssumptionEvidenceDigestAssumption] = Field(
        default_factory=list
    )
    top_challenged: list[AssumptionEvidenceDigestAssumption] = Field(
        default_factory=list
    )
    assumptions: list[AssumptionEvidenceDigestAssumption] = Field(
        default_factory=list
    )
    next_action: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "EVIDENCE_RESULT_LITERAL",
    "EvidenceCreate",
    "EvidenceOut",
    "AssumptionEvidenceScorecardOut",
    "AssumptionEvidenceDigestAssumption",
    "AssumptionEvidenceDigestOut",
]
