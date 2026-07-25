"""Tests for count_above_threshold helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_above_threshold


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_count_above_threshold_zero_when_empty() -> None:
    assert count_above_threshold([], threshold=0.01) == 0


def test_count_above_threshold_counts_only_high_deltas() -> None:
    scenarios = [
        _scenario(1, 0.05),
        _scenario(2, 0.005),
        _scenario(3, 0.20),
    ]

    assert count_above_threshold(scenarios, threshold=0.01) == 2