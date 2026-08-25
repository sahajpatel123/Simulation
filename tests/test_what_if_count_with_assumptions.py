"""Tests for count_with_assumptions helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import count_with_assumptions


def _scenario(sim_id: int, *, with_assumption: bool) -> WhatIfOut:
    assumptions = []
    if with_assumption:
        assumptions = [
            WhatIfAssumption(text="Pricing too expensive", sensitivity="HIGH", impact_score=7),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, assumptions_applied=assumptions)


def test_count_with_assumptions_zero_when_empty() -> None:
    assert count_with_assumptions([]) == 0


def test_count_with_assumptions_counts_only_with_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=True),
        _scenario(2, with_assumption=False),
        _scenario(3, with_assumption=True),
    ]

    assert count_with_assumptions(scenarios) == 2
