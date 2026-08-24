"""Tests for assumptions_ratio helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import assumptions_ratio


def _scenario(sim_id: int, *, with_assumption: bool) -> WhatIfOut:
    assumptions = []
    if with_assumption:
        assumptions = [
            WhatIfAssumption(text="Pricing too expensive", sensitivity="HIGH", impact_score=5),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, assumptions_applied=assumptions)


def test_ratio_zero_when_empty_input() -> None:
    assert assumptions_ratio([]) == 0.0


def test_ratio_zero_when_no_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=False),
        _scenario(2, with_assumption=False),
    ]

    assert assumptions_ratio(scenarios) == 0.0


def test_ratio_one_when_all_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=True),
        _scenario(2, with_assumption=True),
    ]

    assert assumptions_ratio(scenarios) == 1.0


def test_ratio_partial() -> None:
    scenarios = [
        _scenario(1, with_assumption=True),
        _scenario(2, with_assumption=False),
        _scenario(3, with_assumption=False),
        _scenario(4, with_assumption=True),
    ]

    assert assumptions_ratio(scenarios) == 0.5
