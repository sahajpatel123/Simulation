"""Pydantic schema for the combined validation-dashboard endpoint.

``GET /projects/{project_id}/validation-dashboard`` answers the founder's
"where do I stand on de-risking?" question in a single response by composing
four simulation-independent builders:

* :class:`AssumptionEvidenceDigestOut` — project-level coverage / de-risked /
  challenged / pending counts, result and method histograms, and the next
  highest-leverage experiments to run.
* :class:`ValidationTimelineMilestonesOut` — first-occurrence event IDs for
  each meaningful validation state, so a founder can jump straight to the
  first PASS or first FAIL.
* :class:`ValidationMomentumOut` — evidence cadence (events/week, recent
  trend) and a projected horizon to full coverage / a de-risked target.
* evidence freshness (:class:`EvidenceStalenessSummaryOut`) — how old each
  assumption's latest evidence is, plus the top of the re-test queue.

The full event list and progress snapshots of the validation timeline are
deliberately omitted from the dashboard to keep the payload lean — a founder
drilling into event-by-event detail can still hit the timeline endpoint
directly.  Likewise the freshness section carries the summary rollup and at
most three re-test items; the complete queue lives in the
``/evidence-freshness`` endpoint and its export.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.assumption_evidence import AssumptionEvidenceDigestOut
from app.schemas.evidence_staleness import (
    EvidenceStalenessRowOut,
    EvidenceStalenessSummaryOut,
)
from app.schemas.validation_momentum import ValidationMomentumOut
from app.schemas.validation_timeline import ValidationTimelineMilestonesOut

DASHBOARD_MODEL: str = "validation_dashboard_v2"

__all__ = ["DASHBOARD_MODEL", "ValidationDashboardOut"]


class ValidationDashboardOut(BaseModel):
    """Combined validation overview for a project.

    Aggregates the evidence digest, timeline milestones, momentum forecast,
    and evidence-freshness rollup so the frontend can render a single
    de-risking dashboard with one API call instead of four.
    """

    project_id: int
    evidence_digest: AssumptionEvidenceDigestOut = Field(
        default_factory=AssumptionEvidenceDigestOut,
    )
    timeline_milestones: ValidationTimelineMilestonesOut = Field(
        default_factory=ValidationTimelineMilestonesOut,
    )
    momentum: ValidationMomentumOut = Field(
        default_factory=ValidationMomentumOut,
    )
    evidence_freshness: EvidenceStalenessSummaryOut | None = None
    retest_queue_top: list[EvidenceStalenessRowOut] = Field(
        default_factory=list,
    )
    meta: dict[str, Any] = Field(default_factory=dict)
