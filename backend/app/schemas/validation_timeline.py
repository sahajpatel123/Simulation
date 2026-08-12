"""Pydantic schemas for the assumption-validation timeline endpoint.

``GET /projects/{project_id}/assumption-validation-timeline`` shows how a
project's de-risking evidence accumulated over time. Instead of the current
snapshot returned by ``/evidence-digest``, the timeline exposes every logged
experiment in chronological order plus the project's cumulative validation
progress after each event (de-risked / challenged / inconclusive / pending
counts and the validation score).

The timeline is deliberately simulation-independent, matching the evidence
digest: a founder can track validation progress before the first simulation
completes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ValidationTimelineEventOut(BaseModel):
    """One logged evidence event in the project timeline."""

    event_id: int
    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    sensitivity: str = "MEDIUM"
    method: str = ""
    method_label: str = ""
    result: str = ""
    observed_metric: float | None = None
    notes: str | None = None
    created_at: datetime | None = None
    # Confidence tier implied by this event's result when decisive.
    derived_confidence: str | None = None
    # DE_RISKED / CHALLENGED / INCONCLUSIVE / PENDING after this event.
    status_after: str = "INCONCLUSIVE"


class ValidationProgressSnapshotOut(BaseModel):
    """Cumulative project validation progress after one timeline event."""

    event_id: int
    created_at: datetime | None = None
    evidence_rows: int = Field(default=0, ge=0)
    assumptions_with_evidence: int = Field(default=0, ge=0)
    de_risked_count: int = Field(default=0, ge=0)
    challenged_count: int = Field(default=0, ge=0)
    inconclusive_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    validation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_coverage_pct: float | None = Field(default=None, ge=0.0, le=1.0)


class ValidationTimelineAssumptionOut(BaseModel):
    """Per-assumption summary with the evidence events that moved it."""

    assumption_id: int
    assumption_text: str = ""
    category: str | None = None
    sensitivity: str = "MEDIUM"
    evidence_count: int = Field(default=0, ge=0)
    # DE_RISKED / CHALLENGED / INCONCLUSIVE / PENDING.
    status: str = "PENDING"
    first_evidence_event_id: int | None = None
    latest_evidence_event_id: int | None = None
    first_de_risked_event_id: int | None = None
    first_challenged_event_id: int | None = None


class ValidationTimelineMilestonesOut(BaseModel):
    """First time each meaningful validation state occurred."""

    first_evidence_event_id: int | None = None
    last_evidence_event_id: int | None = None
    first_de_risked_event_id: int | None = None
    first_challenged_event_id: int | None = None
    first_inconclusive_event_id: int | None = None


class AssumptionValidationTimelineOut(BaseModel):
    """Full response for the project assumption-validation timeline."""

    project_id: int
    total_assumptions: int = Field(default=0, ge=0)
    total_evidence_rows: int = Field(default=0, ge=0)
    events: list[ValidationTimelineEventOut] = Field(default_factory=list)
    progress: list[ValidationProgressSnapshotOut] = Field(
        default_factory=list
    )
    assumptions: list[ValidationTimelineAssumptionOut] = Field(
        default_factory=list
    )
    milestones: ValidationTimelineMilestonesOut = Field(
        default_factory=ValidationTimelineMilestonesOut
    )
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AssumptionValidationTimelineOut",
    "ValidationProgressSnapshotOut",
    "ValidationTimelineAssumptionOut",
    "ValidationTimelineEventOut",
    "ValidationTimelineMilestonesOut",
]
