"""Tests for all_recommendation_titles helper."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation
from app.simulation.what_if import all_recommendation_titles


def _scenario(sim_id: int, titles: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=sim_id,
        project_id=sim_id,
        recommendations=[
            WhatIfRecommendation(priority=idx + 1, title=title, rationale="r")
            for idx, title in enumerate(titles)
        ],
    )


def test_all_recommendation_titles_empty_when_empty_input() -> None:
    assert all_recommendation_titles([]) == []


def test_all_recommendation_titles_empty_when_no_recommendations() -> None:
    scenarios = [_scenario(1, []), _scenario(2, [])]

    assert all_recommendation_titles(scenarios) == []


def test_all_recommendation_titles_returns_all_in_input_order() -> None:
    scenarios = [
        _scenario(1, ["first", "second"]),
        _scenario(2, ["third"]),
        _scenario(3, []),
        _scenario(4, ["fourth"]),
    ]

    assert all_recommendation_titles(scenarios) == ["first", "second", "third", "fourth"]