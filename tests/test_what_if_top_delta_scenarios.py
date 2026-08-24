"""Tests for top_delta_scenarios helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import top_delta_scenarios


def _scenario(sim_id: int, delta: float) -> WhatIfOut:
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, conversion_delta=delta)


def test_top_delta_scenarios_returns_highest_n() -> None:
    scenarios = [
        _scenario(1, 0.05),
        _scenario(2, 0.10),
        _scenario(3, 0.20),
    ]

    top = top_delta_scenarios(scenarios, n=2)

    assert [s.simulation_id for s in top] == [3, 2]


def test_top_delta_scenarios_returns_empty_for_n_zero() -> None:
    scenarios = [_scenario(1, 0.05), _scenario(2, 0.10)]

    assert top_delta_scenarios(scenarios, n=0) == []


def test_top_delta_scenarios_returns_empty_for_empty_input() -> None:
    assert top_delta_scenarios([], n=3) == []


def test_top_delta_scenarios_handles_negative_deltas() -> None:
    scenarios = [
        _scenario(1, -0.05),
        _scenario(2, 0.10),
        _scenario(3, -0.02),
    ]

    top = top_delta_scenarios(scenarios, n=1)

    assert [s.simulation_id for s in top] == [2]
