"""Tests for the per-project recommendations digest helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

import pytest


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import recommendations_digest

    assert set(recommendations_digest.__all__) == {
        "MAX_TOP",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_recommendations_digest",
    }


def test_digest_empty_returns_zero_state() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(None, None)
    assert out["recommendation_count"] == 0
    assert out["top_recommendations"] == []
    assert out["critical_failure_count"] == 0
    assert out["quick_win_count"] == 0


def test_digest_composes_premortem_critical() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {
                    "title": "Founder burns out",
                    "severity": "CRITICAL",
                    "description": "...",
                    "impact": 9,
                    "probability": 0.7,
                },
            ],
        },
        intervention_digest={},
    )
    assert out["critical_failure_count"] == 1
    assert out["top_recommendations"][0]["title"] == (
        "Founder burns out"
    )


def test_digest_composes_intervention_quick_wins() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={},
        intervention_digest={
            "top_interventions": [
                {
                    "title": "Cut the price 20%",
                    "description": "...",
                    "difficulty": "LOW",
                    "priority_score": 0.95,
                },
            ],
        },
    )
    assert out["quick_win_count"] == 1
    assert "Quick win" in out["top_recommendations"][0]["title"]


def test_digest_no_quick_win_when_high_difficulty() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={},
        intervention_digest={
            "top_interventions": [
                {
                    "title": "Hard",
                    "description": "...",
                    "difficulty": "HIGH",
                    "priority_score": 0.95,
                },
            ],
        },
    )
    assert out["quick_win_count"] == 0


def test_digest_no_quick_win_when_priority_below_threshold() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={},
        intervention_digest={
            "top_interventions": [
                {
                    "title": "Borderline",
                    "description": "...",
                    "difficulty": "LOW",
                    "priority_score": 0.50,
                },
            ],
        },
    )
    assert out["quick_win_count"] == 0


def test_digest_top_recommendations_sorted_by_score() -> None:
    """Items are ranked by max(impact, priority) DESC."""
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {"title": "low", "severity": "MEDIUM",
                 "impact": 1, "description": "..."},
            ],
        },
        intervention_digest={
            "top_interventions": [
                {"title": "high", "description": "...",
                 "difficulty": "LOW", "priority_score": 0.95},
                {"title": "mid", "description": "...",
                 "difficulty": "LOW", "priority_score": 0.6},
            ],
        },
    )
    # high (0.95) first, then mid (0.6), then low (1.0).
    # The helper prepends "Quick win: " to titles when
    # priority_score > 0.70 (see lines 117-120 in
    # recommendations_digest.py) — so "high" surfaces as
    # "Quick win: high" in the output.
    assert [r["title"] for r in out["top_recommendations"]] == [
        "Quick win: high", "mid", "low",
    ]


def test_digest_top_capped() -> None:
    from app.simulation.recommendations_digest import (
        MAX_TOP,
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {
                    "title": f"f{i}", "severity": "MEDIUM",
                    "impact": 1.0 + i, "description": "...",
                }
                for i in range(5)
            ],
        },
        intervention_digest={
            "top_interventions": [
                {
                    "title": f"i{i}", "description": "...",
                    "difficulty": "LOW",
                    "priority_score": 0.5 + i * 0.01,
                }
                for i in range(5)
            ],
        },
    )
    assert len(out["top_recommendations"]) == MAX_TOP


def test_digest_handles_non_dict_entries() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                "not-a-dict",
                None,
                {
                    "title": "x", "severity": "CRITICAL",
                    "impact": 9, "description": "...",
                },
            ],
        },
        intervention_digest={},
    )
    assert out["recommendation_count"] == 1


def test_digest_narrative_mentions_critical() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {"title": "x", "severity": "CRITICAL",
                 "impact": 9, "description": "..."},
            ],
        },
        intervention_digest={},
    )
    assert "critical" in out["narrative"].lower()


def test_digest_narrative_mentions_quick_win_when_present() -> None:
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={},
        intervention_digest={
            "top_interventions": [
                {"title": "x", "description": "...",
                 "difficulty": "LOW", "priority_score": 0.95},
            ],
        },
    )
    assert "quick" in out["narrative"].lower()


def test_digest_key_signals_critical_when_many() -> None:
    from app.simulation.recommendations_digest import (
        SIGNAL_CRITICAL,
        build_recommendations_digest,
    )

    out = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {"title": f"f{i}", "severity": "CRITICAL",
                 "impact": 9, "description": "..."}
                for i in range(2)
            ],
        },
        intervention_digest={},
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "critical_failure_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_schema_round_trip() -> None:
    from app.schemas.project import RecommendationsDigestOut
    from app.simulation.recommendations_digest import (
        build_recommendations_digest,
    )

    payload = build_recommendations_digest(
        premortem_digest={
            "top_failure_modes": [
                {"title": "x", "severity": "CRITICAL",
                 "impact": 9, "description": "..."},
            ],
        },
        intervention_digest={},
    )
    out = RecommendationsDigestOut(**payload)
    assert out.recommendation_count == 1
    assert out.critical_failure_count == 1