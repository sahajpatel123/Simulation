"""Tests for scenarios_with_assumptions batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import scenarios_with_assumptions


def _scenario(sim_id: int, *, with_assumption: bool) -> WhatIfOut:
    assumptions = []
    if with_assumption:
        assumptions = [
            WhatIfAssumption(text="Pricing too expensive", sensitivity="HIGH", impact_score=7),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, assumptions_applied=assumptions)


def test_filter_keeps_scenarios_with_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=True),
        _scenario(2, with_assumption=False),
        _scenario(3, with_assumption=True),
    ]

    filtered = scenarios_with_assumptions(scenarios)

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=False),
        _scenario(2, with_assumption=False),
    ]

    assert scenarios_with_assumptions(scenarios) == []


def test_filter_returns_empty_for_empty_input() -> None:
    assert scenarios_with_assumptions([]) == []
