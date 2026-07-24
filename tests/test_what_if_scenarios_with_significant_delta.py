"""Tests for scenarios_with_significant_delta filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenarios_with_significant_delta


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_filter_keeps_above_default_threshold() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, -0.03), _scenario(3, 0.005)]

    filtered = scenarios_with_significant_delta(scenarios)

    assert [s.simulation_id for s in filtered] == [1, 2]


def test_filter_respects_custom_threshold() -> None:
    scenarios = [_scenario(1, 0.005), _scenario(2, 0.05)]

    filtered = scenarios_with_significant_delta(scenarios, threshold=0.01)

    assert [s.simulation_id for s in filtered] == [2]


def test_filter_returns_empty_when_all_below_threshold() -> None:
    scenarios = [_scenario(1, 0.0), _scenario(2, 0.001), _scenario(3, -0.001)]

    filtered = scenarios_with_significant_delta(scenarios)

    assert filtered == []