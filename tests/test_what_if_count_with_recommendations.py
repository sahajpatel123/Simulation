"""Tests for count_with_recommendations helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import count_with_recommendations


def _scenario(sim_id: int, *, with_recommendation: bool) -> WhatIfOut:
    recommendations = []
    if with_recommendation:
        recommendations = [
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, recommendations=recommendations)


def test_count_zero_when_empty() -> None:
    assert count_with_recommendations([]) == 0


def test_count_zero_when_no_recommendations() -> None:
    scenarios = [_scenario(1, with_recommendation=False), _scenario(2, with_recommendation=False)]

    assert count_with_recommendations(scenarios) == 0


def test_count_with_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=False),
        _scenario(3, with_recommendation=True),
    ]

    assert count_with_recommendations(scenarios) == 2
