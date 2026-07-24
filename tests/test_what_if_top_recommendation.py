"""Tests for WhatIfOut.top_recommendation()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation


def _rec(priority: int, title: str) -> WhatIfRecommendation:
    return WhatIfRecommendation(
        priority=priority,
        title=title,
        rationale="test",
        estimated_lift=0.0,
        affected_stages=[],
    )


def test_top_recommendation_returns_none_when_empty() -> None:
    assert WhatIfOut(simulation_id=1, project_id=1).top_recommendation() is None


def test_top_recommendation_returns_only_recommendation() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[_rec(2, "Only")],
    )

    assert out.top_recommendation() is not None
    assert out.top_recommendation().title == "Only"


def test_top_recommendation_returns_lowest_priority() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[_rec(3, "third"), _rec(1, "first"), _rec(2, "second")],
    )

    top = out.top_recommendation()
    assert top is not None
    assert top.priority == 1
    assert top.title == "first"


def test_top_recommendation_is_stable_for_ties() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[_rec(2, "first"), _rec(2, "second")],
    )

    assert out.top_recommendation().title == "first"