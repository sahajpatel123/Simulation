"""Tests for count_scenarios helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import count_scenarios


def _scenario(sim_id: int) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id)


def test_count_scenarios_for_empty_input() -> None:
    assert count_scenarios([]) == 0


def test_count_scenarios_returns_list_length() -> None:
    assert count_scenarios([_scenario(1), _scenario(2), _scenario(3)]) == 3


def test_count_scenarios_returns_int() -> None:
    assert isinstance(count_scenarios([]), int)
    assert isinstance(count_scenarios([_scenario(1)]), int)