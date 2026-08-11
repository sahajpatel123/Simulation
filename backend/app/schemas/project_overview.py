"""Pydantic schemas for the one-call per-project overview digest.

``GET /api/v1/projects/{project_id}/overview`` composes the eight existing
per-project digests (status banner, latest snapshot, confidence explainer,
next action, stale check, convergence, health, outcomes digest) into a single
dashboard payload with an overall verdict.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectOverviewSubsystem(BaseModel):
    """One normalised project-digest row from the overview."""

    key: str = ""
    label: str = ""
    verdict: str = "HEALTHY"
    healthy: bool = True
    summary: str = ""
    headline: dict[str, Any] = Field(default_factory=dict)


class ProjectOverviewKeySignal(BaseModel):
    """One aggregated signal row for the overview tile."""

    label: str = ""
    value: Any = None
    severity: str = "ok"
    display: str = ""


class ProjectOverviewOut(BaseModel):
    """Response from ``GET /api/v1/projects/{project_id}/overview``."""

    project_id: int = Field(default=0, ge=0)
    generated_at: str = ""
    overall_verdict: str = "EMPTY"
    healthy: bool = True
    headline: str = ""
    narrative: str = ""
    key_signals: list[ProjectOverviewKeySignal] = Field(
        default_factory=list
    )
    unhealthy_components: list[str] = Field(default_factory=list)
    subsystems: list[ProjectOverviewSubsystem] = Field(
        default_factory=list
    )
    panels: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ProjectOverviewKeySignal",
    "ProjectOverviewOut",
    "ProjectOverviewSubsystem",
]
