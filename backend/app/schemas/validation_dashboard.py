"""Pydantic schema for the combined validation-dashboard endpoint.

``GET /projects/{project_id}/validation-dashboard`` answers the founder's
"where do I stand on de-risking?" question in a single response by composing
three simulation-independent builders:

* :class:`AssumptionEvidenceDigestOut` — project-level coverage / de-risked /
  challenged / pending counts, result and method histograms, and the next
  highest-leverage experiments to run.
* :class:`ValidationTimelineMilestonesOut` — first-occurrence event IDs for
  each meaningful validation state, so a founder can jump straight to the
  first PASS or first FAIL.
* :class:`ValidationMomentumOut` — evidence cadence (events/week, recent
  trend) and a projected horizon to full coverage / a de-risked target.

The full event list and progress snapshots of the validation timeline are
deliberately omitted from the dashboard to keep the payload lean — a founder
drilling into event-by-event detail can still hit the timeline endpoint
directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.assumption_evidence import AssumptionEvidenceDigestOut
from app.schemas.validation_momentum import ValidationMomentumOut
from app.schemas.validation_timeline import ValidationTimelineMilestonesOut

DASHBOARD_MODEL: str = "validation_dashboard_v1"


class ValidationDashboardOut(BaseModel):
    """Combined validation overview for a project.

    Aggregates the evidence digest, timeline milestones, and momentum
    forecast so the frontend can render a single de-risking dashboard with
    one API call instead of three.
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
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = ["DASHBOARD_MODEL", "ValidationDashboardOut"]
