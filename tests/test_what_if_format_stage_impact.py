"""Tests for format_stage_impact."""
from __future__ import annotations

from app.schemas.what_if import StageImpact
from app.simulation.what_if import format_stage_impact


def _impact(delta: float, base: float = 0.6, projected: float = 0.5) -> StageImpact:
    return StageImpact(
        stage="BROWSE",
        transition="BROWSE→CONSIDER",
        base_rate=base,
        projected_rate=projected,
        delta=delta,
        affected_by=[],
    )


def test_format_stage_impact_negative_delta() -> None:
    impact = _impact(-0.07)
    line = format_stage_impact(impact)

    assert "BROWSE→CONSIDER" in line
    assert "0.6000→0.5000" in line
    assert "(-0.0700)" in line


def test_format_stage_impact_positive_delta() -> None:
    impact = _impact(0.05, base=0.5, projected=0.55)
    line = format_stage_impact(impact)

    assert "(+0.0500)" in line


def test_format_stage_impact_zero_delta() -> None:
    impact = _impact(0.0, base=0.6, projected=0.6)
    line = format_stage_impact(impact)

    assert "(+0.0000)" in line