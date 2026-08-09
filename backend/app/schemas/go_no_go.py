"""Pydantic schemas for the project go/no-go digest.

``GET /api/v1/projects/{id}/go-no-go`` answers the founder's final
pre-launch question — "should I ship this?" — by consolidating six
existing deterministic reads into one launch scorecard: launch
readiness, premortem risk posture, competitive position, simulation
data trust, data freshness, and assumption coverage. Each pillar
carries a 0..100 score and verdict; the digest combines available
pillars into an overall go/no-go score with hard gates, strengths,
risks and top actions.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PILLAR_VERDICT_LITERAL = Literal[
    "STRONG",
    "MODERATE",
    "WEAK",
    "INSUFFICIENT_DATA",
]

GO_NO_GO_VERDICT_LITERAL = Literal[
    "GO",
    "CONDITIONAL_GO",
    "NO_GO",
    "INSUFFICIENT_DATA",
]


class GoNoGoPillar(BaseModel):
    """One scored pillar of the go/no-go digest."""

    key: str
    label: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    verdict: PILLAR_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    summary: str = ""


class GoNoGoGate(BaseModel):
    """One launch gate — a pass/fail condition that must hold for GO."""

    id: str
    label: str = ""
    evaluated: bool = False
    passed: bool | None = None
    detail: str = ""


class GoNoGoOut(BaseModel):
    """Full go/no-go response for a project."""

    project_id: int
    latest_simulation_id: int | None = None
    go_no_go_score: int | None = Field(default=None, ge=0, le=100)
    verdict: GO_NO_GO_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    verdict_label: str = ""
    pillars: list[GoNoGoPillar] = Field(default_factory=list)
    gates: list[GoNoGoGate] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    top_actions: list[str] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "GoNoGoPillar",
    "GoNoGoGate",
    "GoNoGoOut",
]
