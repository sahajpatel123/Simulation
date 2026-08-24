"""Tests for total_assumption_count helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfAssumption, WhatIfOut
from app.simulation.what_if import total_assumption_count


def _scenario(sim_id: int, assumption_count: int) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        assumptions_applied=[
            WhatIfAssumption(text=f"assumption {idx}", sensitivity="HIGH", impact_score=5)
            for idx in range(assumption_count)
        ],
    )


def test_total_assumption_count_zero_when_empty() -> None:
    assert total_assumption_count([]) == 0


def test_total_assumption_count_sums_across_scenarios() -> None:
    scenarios = [_scenario(1, 2), _scenario(2, 3), _scenario(3, 0)]

    assert total_assumption_count(scenarios) == 5


def test_total_assumption_count_returns_zero_when_no_assumptions() -> None:
    scenarios = [_scenario(1, 0), _scenario(2, 0)]

    assert total_assumption_count(scenarios) == 0
