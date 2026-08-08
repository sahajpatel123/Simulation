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

from pydantic import BaseModel, Field

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


__all__ = [
    "EVIDENCE_RESULT_LITERAL",
    "EvidenceCreate",
    "EvidenceOut",
    "AssumptionEvidenceScorecardOut",
]
