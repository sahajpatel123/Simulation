"""Tests for format_stage_impact_label helper."""
from __future__ import annotations

from app.schemas.what_if import StageImpact
from app.simulation.what_if import format_stage_impact_label


def _impact(base: float, projected: float, delta: float) -> StageImpact:
    return StageImpact(
        stage="BROWSE",
        transition="BROWSE→CONSIDER",
        base_rate=base,
        projected_rate=projected,
        delta=delta,
        affected_by=[],
    )


def test_format_stage_impact_label_for_regression() -> None:
    impact = _impact(0.62, 0.55, -0.07)
    assert format_stage_impact_label(impact) == "0.6200 → 0.5500 (-0.0700)"


def test_format_stage_impact_label_for_improvement() -> None:
    impact = _impact(0.50, 0.65, 0.15)
    assert format_stage_impact_label(impact) == "0.5000 → 0.6500 (+0.1500)"


def test_format_stage_impact_label_for_zero_delta() -> None:
    impact = _impact(0.50, 0.50, 0.0)
    assert format_stage_impact_label(impact) == "0.5000 → 0.5000 (+0.0000)"
