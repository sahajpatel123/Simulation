"""Tests for the what-if recommendation list cap + dedupe helper."""
from __future__ import annotations


from app.simulation.what_if import _dedupe_and_cap_recommendations, build_what_if_scenario
from app.schemas.what_if import WhatIfRecommendation


def _rec(title: str, priority: int = 1) -> WhatIfRecommendation:
    return WhatIfRecommendation(
        priority=priority,
        title=title,
        rationale="test rationale",
        estimated_lift=0.0,
        affected_stages=[],
    )


def test_dedupe_keeps_first_title_only() -> None:
    recs = [
        _rec("Same title"),
        _rec("Same title"),
        _rec("Different"),
    ]

    deduped = _dedupe_and_cap_recommendations(recs)

    assert [rec.title for rec in deduped] == ["Same title", "Different"]


def test_cap_limits_recommendation_length() -> None:
    recs = [_rec(f"Title {idx}", priority=idx) for idx in range(10)]

    deduped = _dedupe_and_cap_recommendations(recs, max_items=4)

    assert len(deduped) == 4
    assert [rec.title for rec in deduped] == [f"Title {idx}" for idx in range(4)]


def test_dedupe_then_cap_preserves_order() -> None:
    recs = [
        _rec("A"),
        _rec("A"),
        _rec("B"),
        _rec("C"),
        _rec("B"),
    ]

    deduped = _dedupe_and_cap_recommendations(recs, max_items=10)

    assert [rec.title for rec in deduped] == ["A", "B", "C"]


def test_what_if_response_caps_recommendations() -> None:
    out = build_what_if_scenario(
        simulation_id=42,
        project_id=42,
        base_results={
            "population_weighted_conversion": 0.05,
            "mean_revenue": 999.0,
            "product_type_detected": "saas",
        },
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        existing_assumptions=[],
        new_assumptions=[
            {
                "text": "Pricing is too expensive for tier-3 users",
                "sensitivity": "CRITICAL",
                "impact_score": 9.0,
            }
        ],
    )

    assert len(out.recommendations) <= 6
    titles = [rec.title for rec in out.recommendations]
    assert len(titles) == len(set(titles))