"""
Pydantic schemas for the simulation-comparison endpoint
``GET /api/v1/simulations/{id}/compare/{baseline_id}``.

Founders re-run a simulation after changing assumptions, price, or
positioning — and then want the *diff*, not a second wall of numbers.
The comparison answers three questions: did predicted conversion move
(and by how much), which funnel stage changed its drop-off, and which
consumer clusters drove the shift.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

VERDICT_LITERAL = Literal["IMPROVED", "REGRESSED", "FLAT"]
DIRECTION_LITERAL = Literal["IMPROVED", "WORSENED", "UNCHANGED"]

# Absolute change below this many rate points is treated as noise-flat.
FLAT_THRESHOLD_RATE_POINTS: float = 0.001


class HeadlineComparison(BaseModel):
    """Top-line movement between the two simulations."""

    conversion_before: float = Field(default=0.0, ge=0.0, le=1.0)
    conversion_after: float = Field(default=0.0, ge=0.0, le=1.0)
    conversion_delta_pp: float = 0.0  # percentage points (after - before)
    conversion_delta_pct: float | None = Field(
        default=None,
        description="Relative change vs baseline; null when baseline is zero.",
    )
    verdict: VERDICT_LITERAL = "FLAT"
    revenue_before: float = 0.0
    revenue_after: float = 0.0
    confidence_before: float | None = None
    confidence_after: float | None = None
    signal_quality_before: float | None = None
    signal_quality_after: float | None = None
    worst_drop_off_stage_before: str = ""
    worst_drop_off_stage_after: str = ""
    worst_stage_changed: bool = False


class StageDelta(BaseModel):
    """Drop-off change for one funnel state present in either run."""

    state: str
    drop_off_before: float | None = None
    drop_off_after: float | None = None
    drop_off_delta_pp: float = 0.0


class ClusterDelta(BaseModel):
    """Conversion change for one consumer cluster."""

    cluster_id: str
    conversion_before: float | None = None
    conversion_after: float | None = None
    conversion_delta_pp: float = 0.0
    direction: DIRECTION_LITERAL = "UNCHANGED"


class SimulationRunDiffOut(BaseModel):
    """Full response for the run-vs-run comparison endpoint.

    Distinct from ``simulation_comparison.SimulationComparisonOut`` (the
    domain-findings diff): this schema carries the funnel-level diff —
    headline conversion movement, stage drop-off changes, cluster movers.
    """

    simulation_id: int
    baseline_id: int
    project_id: int | None = None
    headline: HeadlineComparison
    stage_deltas: list[StageDelta] = Field(default_factory=list)
    cluster_deltas: list[ClusterDelta] = Field(
        default_factory=list,
        description=(
            "Sorted by absolute impact, largest first; capped at "
            "``meta['clusters_shown']`` rows."
        ),
    )
    clusters_improved: int = 0
    clusters_worsened: int = 0
    biggest_mover: ClusterDelta | None = None
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DIRECTION_LITERAL",
    "FLAT_THRESHOLD_RATE_POINTS",
    "VERDICT_LITERAL",
    "ClusterDelta",
    "HeadlineComparison",
    "SimulationRunDiffOut",
    "StageDelta",
]
