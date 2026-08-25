"""Tests for with_assumptions_ratio helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import with_assumptions_ratio


def _scenario(sim_id: int, *, with_assumption: bool) -> WhatIfOut:
    assumptions = []
    if with_assumption:
        assumptions = [
            WhatIfAssumption(text="Pricing too expensive", sensitivity="HIGH", impact_score=5),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, assumptions_applied=assumptions)


def test_with_assumptions_ratio_zero_when_empty() -> None:
    assert with_assumptions_ratio([]) == 0.0


def test_with_assumptions_ratio_counts_only_with_assumptions() -> None:
    scenarios = [
        _scenario(1, with_assumption=True),
        _scenario(2, with_assumption=False),
        _scenario(3, with_assumption=True),
    ]

    assert with_assumptions_ratio(scenarios) == 2 / 3
