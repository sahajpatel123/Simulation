"""Tests for scenarios_above_threshold batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_above_threshold


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_above_threshold_keeps_only_high_deltas() -> None:
    scenarios = [
        _scenario(1, 0.05),
        _scenario(2, 0.005),
        _scenario(3, 0.20),
    ]

    filtered = scenarios_above_threshold(scenarios, threshold=0.01)

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_above_threshold_respects_custom_threshold() -> None:
    scenarios = [
        _scenario(1, 0.005),
        _scenario(2, 0.05),
    ]

    filtered = scenarios_above_threshold(scenarios, threshold=0.01)

    assert [s.simulation_id for s in filtered] == [2]


def test_above_threshold_returns_empty_for_empty_input() -> None:
    assert scenarios_above_threshold([], threshold=0.01) == []


def test_above_threshold_handles_zero_threshold() -> None:
    scenarios = [_scenario(1, 0.0), _scenario(2, 0.05), _scenario(3, -0.05)]

    filtered = scenarios_above_threshold(scenarios, threshold=0.0)

    # threshold=0.0 keeps delta >= 0 (0 included, negatives excluded)
    assert [s.simulation_id for s in filtered] == [1, 2]