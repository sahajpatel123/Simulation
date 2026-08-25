"""Tests for scenarios_with_recommendations batch filter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation


def _scenario(sim_id: int, *, with_recommendation: bool) -> WhatIfOut:
    recommendations = []
    if with_recommendation:
        recommendations = [
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ]
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        recommendations=recommendations,
    )


def test_filter_keeps_scenarios_with_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=False),
        _scenario(3, with_recommendation=True),
    ]

    filtered = [
        scenario for scenario in scenarios if scenario.has_recommendations()
    ]

    assert [s.simulation_id for s in filtered] == [1, 3]


def test_filter_returns_empty_when_no_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=False),
        _scenario(2, with_recommendation=False),
    ]

    filtered = [
        scenario for scenario in scenarios if scenario.has_recommendations()
    ]

    assert filtered == []
