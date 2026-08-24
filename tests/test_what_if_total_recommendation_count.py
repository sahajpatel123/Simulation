"""Tests for total_recommendation_count helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import total_recommendation_count


def _scenario(sim_id: int, recommendation_count: int) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        recommendations=[
            WhatIfRecommendation(priority=idx + 1, title=f"rec{idx}", rationale="r")
            for idx in range(recommendation_count)
        ],
    )


def test_total_recommendation_count_zero_when_empty() -> None:
    assert total_recommendation_count([]) == 0


def test_total_recommendation_count_sums_across_scenarios() -> None:
    scenarios = [_scenario(1, 2), _scenario(2, 3), _scenario(3, 0)]

    assert total_recommendation_count(scenarios) == 5


def test_total_recommendation_count_returns_zero_when_no_recommendations() -> None:
    scenarios = [_scenario(1, 0), _scenario(2, 0)]

    assert total_recommendation_count(scenarios) == 0
