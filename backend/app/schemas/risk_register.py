"""
Pydantic schemas for the per-project risk register digest
``GET /projects/{id}/risk-register``.

The digest merges every deterministic risk source already persisted for a
project - premortem failure modes, stress-test kill shots, competitive
threats, and simulation findings - into one score-normalized, ranked
register with severities normalized to CRITICAL / MAJOR / MINOR / INFO.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RISK_SOURCE_LITERAL = Literal[
    "PRE_MORTEM",
    "STRESS_TEST",
    "COMPETITIVE",
    "SIMULATION_FINDING",
]
RISK_SEVERITY_LITERAL = Literal["CRITICAL", "MAJOR", "MINOR", "INFO"]
RISK_LEVEL_LITERAL = Literal["LOW", "MODERATE", "HIGH", "SEVERE"]


class RiskItemOut(BaseModel):
    """One normalized risk in the register."""

    id: str
    source: RISK_SOURCE_LITERAL
    category: str
    title: str
    description: str = ""
    severity: RISK_SEVERITY_LITERAL = "MINOR"
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    impact: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    recommended_action: str = ""
    metric: str | None = None


class RiskRegisterOut(BaseModel):
    """Response from ``GET /projects/{id}/risk-register``.

    ``total_risks`` / breakdowns cover every deduplicated risk; ``risks``
    is the ranked, capped slice a founder should act on first.
    """

    project_id: int
    generated_at: str = ""
    total_risks: int = Field(default=0, ge=0)
    top_risk_count: int = Field(default=0, ge=0)
    overall_risk_level: RISK_LEVEL_LITERAL = "LOW"
    top_risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    severity_breakdown: dict[str, int] = Field(default_factory=dict)
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    risks: list[RiskItemOut] = Field(default_factory=list)
    narrative: str = ""
    key_signals: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "RISK_LEVEL_LITERAL",
    "RISK_SEVERITY_LITERAL",
    "RISK_SOURCE_LITERAL",
    "RiskItemOut",
    "RiskRegisterOut",
]
