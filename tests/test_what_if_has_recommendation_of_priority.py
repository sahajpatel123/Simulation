"""Tests for WhatIfOut.has_recommendation_of_priority()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation


def _scenario(priorities: list[int]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[
            WhatIfRecommendation(priority=priority, title=f"p{priority}", rationale="r")
            for priority in priorities
        ],
    )


def test_has_recommendation_of_priority_true_when_present() -> None:
    assert _scenario([1, 2, 3]).has_recommendation_of_priority(2) is True


def test_has_recommendation_of_priority_false_when_absent() -> None:
    assert _scenario([1, 3]).has_recommendation_of_priority(2) is False


def test_has_recommendation_of_priority_false_when_no_recommendations() -> None:
    assert _scenario([]).has_recommendation_of_priority(1) is False


def test_has_recommendation_of_priority_uses_exact_int_match() -> None:
    assert _scenario([2]).has_recommendation_of_priority(2) is True
    assert _scenario([2]).has_recommendation_of_priority(20) is False
