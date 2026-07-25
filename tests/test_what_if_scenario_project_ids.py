"""Tests for scenario_project_ids helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import scenario_project_ids


def _scenario(sim_id: int, project_id: int) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=project_id)


def test_scenario_project_ids_empty_when_empty_input() -> None:
    assert scenario_project_ids([]) == []


def test_scenario_project_ids_returns_project_ids() -> None:
    scenarios = [_scenario(1, 10), _scenario(2, 20), _scenario(3, 30)]

    assert scenario_project_ids(scenarios) == [10, 20, 30]


def test_scenario_project_ids_preserves_input_order() -> None:
    scenarios = [_scenario(1, 30), _scenario(2, 10), _scenario(3, 20)]

    assert scenario_project_ids(scenarios) == [30, 10, 20]