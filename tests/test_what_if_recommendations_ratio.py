"""Tests for recommendations_ratio helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import recommendations_ratio


def _scenario(sim_id: int, *, with_recommendation: bool) -> WhatIfOut:
    recommendations = []
    if with_recommendation:
        recommendations = [
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, recommendations=recommendations)


def test_ratio_zero_when_empty_input() -> None:
    assert recommendations_ratio([]) == 0.0


def test_ratio_zero_when_no_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=False),
        _scenario(2, with_recommendation=False),
    ]

    assert recommendations_ratio(scenarios) == 0.0


def test_ratio_one_when_all_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=True),
    ]

    assert recommendations_ratio(scenarios) == 1.0


def test_ratio_partial() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=False),
        _scenario(3, with_recommendation=False),
        _scenario(4, with_recommendation=True),
    ]

    assert recommendations_ratio(scenarios) == 0.5
