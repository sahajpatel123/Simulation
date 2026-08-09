"""Pydantic schemas for the portfolio launch-priority digest.

``GET /api/v1/simulations/portfolio-launch-priority`` answers the
portfolio-level question the per-project go/no-go endpoint cannot:
"I have several projects — which one should I launch first, which
needs fixing before launch, and which should I park until I have
more data?"

The digest reuses the canonical per-project go/no-go verdicts (same
six-pillar score and gates) so the portfolio ranking can never
disagree with a project's own launch scorecard. Each project is
bucketed into ``LAUNCH_NOW`` / ``CONDITIONAL_LAUNCH`` / ``FIX_FIRST``
/ ``PARK`` and the payload emits a ranked ``launch_sequence``, a
single ``top_pick``, and a portfolio-wide ``next_focus`` (the weakest
pillar across the top candidates).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

LAUNCH_BUCKET_LITERAL = Literal[
    "LAUNCH_NOW",
    "CONDITIONAL_LAUNCH",
    "FIX_FIRST",
    "PARK",
]

PORTFOLIO_VERDICT_LITERAL = Literal[
    "READY_TO_LAUNCH",
    "ALMOST_READY",
    "NOT_READY",
    "INSUFFICIENT_DATA",
]


class PortfolioLaunchPriorityItem(BaseModel):
    """One ranked project in the portfolio launch-priority digest."""

    project_id: int
    project_title: str = ""
    rank: int = 0
    bucket: LAUNCH_BUCKET_LITERAL = "PARK"
    go_no_go_score: int | None = Field(default=None, ge=0, le=100)
    verdict: str = "INSUFFICIENT_DATA"
    verdict_label: str = ""
    latest_simulation_id: int | None = None
    latest_simulation_at: str | None = None
    has_outcomes: bool = False
    top_action: str = ""
    reason: str = ""
    weakest_pillar: dict[str, Any] | None = None


class PortfolioLaunchPriorityOut(BaseModel):
    """Full portfolio launch-priority response."""

    project_count: int = 0
    evaluated_count: int = 0
    portfolio_verdict: PORTFOLIO_VERDICT_LITERAL = "INSUFFICIENT_DATA"
    top_pick: PortfolioLaunchPriorityItem | None = None
    buckets: dict[str, list[PortfolioLaunchPriorityItem]] = Field(
        default_factory=dict
    )
    launch_sequence: list[int] = Field(default_factory=list)
    next_focus: str = ""
    narrative: str = ""
    key_signals: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "LAUNCH_BUCKET_LITERAL",
    "PORTFOLIO_VERDICT_LITERAL",
    "PortfolioLaunchPriorityItem",
    "PortfolioLaunchPriorityOut",
]
