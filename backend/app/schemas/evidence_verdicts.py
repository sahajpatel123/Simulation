"""
Pydantic schemas for the per-assumption evidence-verdict endpoint
``GET /api/v1/projects/{project_id}/evidence-verdicts``.

The experiment planner hands every method an explicit success bar ("≥ 30%
would pay the planned price"); founders then log evidence with an
``observed_metric``. This scorecard closes the loop by judging each
assumption's latest decisive evidence against its method's canonical bar —
surfacing on-track / killed verdicts *and* inconsistent records (a PASS
whose metric misses the bar, a FAIL whose metric clears it).

Distinct from the project-level ``go_no_go`` launch digest, which scores
launch pillars rather than individual assumptions.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EVIDENCE_VERDICT_LITERAL = Literal[
    "ON_TRACK",
    "KILLED",
    "INCONSISTENT_PASS",
    "INCONSISTENT_FAIL",
    "NO_METRIC",
    "UNBENCHMARKED_PASS",
    "UNBENCHMARKED_FAIL",
    "INCONCLUSIVE",
    "PENDING",
]


class EvidenceVerdictRow(BaseModel):
    """One assumption judged against its method's success bar."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    evidence_count: int = Field(default=0, ge=0)
    latest_result: str | None = None
    latest_method: str | None = None
    method_label: str = ""
    threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Canonical success bar for the method (fraction); None when "
            "unbenchmarked."
        ),
    )
    observed_metric: float | None = None
    margin_pp: float | None = Field(
        default=None,
        description="(observed_metric - threshold) in percentage points.",
    )
    verdict: EVIDENCE_VERDICT_LITERAL = "PENDING"
    explanation: str = ""


class EvidenceVerdictsOut(BaseModel):
    """Full response for the evidence-verdicts scorecard endpoint."""

    project_id: int
    total_assumptions: int = Field(default=0, ge=0)
    judged_count: int = Field(default=0, ge=0)
    on_track_count: int = Field(default=0, ge=0)
    killed_count: int = Field(default=0, ge=0)
    inconsistent_count: int = Field(default=0, ge=0)
    unjudged_count: int = Field(default=0, ge=0)
    rows: list[EvidenceVerdictRow] = Field(
        default_factory=list,
        description=(
            "Inconsistent and killed assumptions first, then on-track, "
            "then unjudged — attention order, not assumption id order."
        ),
    )
    next_action: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "EVIDENCE_VERDICT_LITERAL",
    "EvidenceVerdictRow",
    "EvidenceVerdictsOut",
]
