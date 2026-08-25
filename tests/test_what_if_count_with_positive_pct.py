"""Tests for count_with_positive_pct helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_with_positive_pct


def _scenario(sim_id: int, delta_pct: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta_pct=delta_pct)


def test_count_with_positive_pct_zero_when_empty() -> None:
    assert count_with_positive_pct([]) == 0


def test_count_with_positive_pct_counts_only_positives() -> None:
    scenarios = [_scenario(1, 12.5), _scenario(2, -5.0), _scenario(3, 7.0), _scenario(4, 0.0)]

    assert count_with_positive_pct(scenarios) == 2
