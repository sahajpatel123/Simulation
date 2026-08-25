"""Tests for sorted_scenarios_by_delta helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import sorted_scenarios_by_delta


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_default_sort_descending() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, 0.20), _scenario(3, 0.10)]

    sorted_scenarios = sorted_scenarios_by_delta(scenarios)

    assert [s.simulation_id for s in sorted_scenarios] == [2, 3, 1]


def test_reverse_false_sorts_ascending() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, 0.20), _scenario(3, 0.10)]

    sorted_scenarios = sorted_scenarios_by_delta(scenarios, reverse=False)

    assert [s.simulation_id for s in sorted_scenarios] == [1, 3, 2]


def test_sort_handles_negative_deltas() -> None:
    scenarios = [_scenario(1, -0.05), _scenario(2, 0.10), _scenario(3, -0.20)]

    sorted_scenarios = sorted_scenarios_by_delta(scenarios)

    assert [s.simulation_id for s in sorted_scenarios] == [2, 1, 3]


def test_sort_returns_empty_for_empty_input() -> None:
    assert sorted_scenarios_by_delta([]) == []
