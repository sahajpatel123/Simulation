"""Tests for with_recommendations_pct helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import with_recommendations_pct


def _scenario(sim_id: int, *, with_recommendation: bool) -> WhatIfOut:
    recommendations = []
    if with_recommendation:
        recommendations = [
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ]
    return WhatIfOut(simulation_id=sim_id, project_id=sim_id, recommendations=recommendations)


def test_with_recommendations_pct_zero_when_empty() -> None:
    assert with_recommendations_pct([]) == 0


def test_with_recommendations_pct_counts_with_recommendations() -> None:
    scenarios = [
        _scenario(1, with_recommendation=True),
        _scenario(2, with_recommendation=False),
        _scenario(3, with_recommendation=True),
    ]

    assert with_recommendations_pct(scenarios) == 2
