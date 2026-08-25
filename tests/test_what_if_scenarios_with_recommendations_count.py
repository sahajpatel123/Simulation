"""Tests for scenarios_with_recommendations_count helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import scenarios_with_recommendations_count


def _scenario(sim_id: int, *, with_recommendation: bool) -> WhatIfOut:
    recommendations = []
    if with_recommendation:
        recommendations = [
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, recommendations=recommendations)


def test_count_zero_when_empty_input() -> None:
    assert scenarios_with_recommendations_count([]) == 0


def test_count_zero_when_no_scenarios_have_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=False),
        _scenario(2, with_recommendation=False),
    ]

    assert scenarios_with_recommendations_count(scenarios) == 0


def test_count_scenarios_with_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=False),
        _scenario(3, with_recommendation=True),
    ]

    assert scenarios_with_recommendations_count(scenarios) == 2
