"""Tests for scenario_ids helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenario_ids


def _scenario(sim_id: int) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id)


def test_scenario_ids_empty_when_empty_input() -> None:
    assert scenario_ids([]) == []


def test_scenario_ids_preserves_input_order() -> None:
    scenarios = [_scenario(3), _scenario(1), _scenario(2)]

    assert scenario_ids(scenarios) == [3, 1, 2]


def test_scenario_ids_returns_ints() -> None:
    scenarios = [_scenario(7), _scenario(11)]

    result = scenario_ids(scenarios)

    assert all(isinstance(value, int) for value in result)
