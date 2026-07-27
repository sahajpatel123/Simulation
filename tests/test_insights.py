"""Tests for the per-user insights helper."""
from __future__ import annotations

import pytest


def test_public_allowlist_matches_callers():
    from app.simulation import insights
    assert set(insights.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_insights",
    }


def test_default_no_data():
    from app.simulation.insights import build_insights
    out = build_insights()
    assert out["has_data"] is False
    assert out["insights"] == []
    assert "welcome" in out["headline"].lower() or "start" in out["narrative"].lower()


def test_healthy_headline_at_score_75():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=3,
        sim_count_total=10,
        decision_count_total=4,
        outcome_count_total=3,
        portfolio_verdict="HEALTHY",
        portfolio_score=75,
    )
    assert "healthy" in out["headline"].lower()


def test_needs_attention_headline_at_score_50():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=3,
        sim_count_total=10,
        decision_count_total=4,
        outcome_count_total=3,
        portfolio_verdict="NEEDS_ATTENTION",
        portfolio_score=50,
    )
    assert "attention" in out["headline"].lower()


def test_at_risk_headline_at_score_25():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=3,
        sim_count_total=10,
        decision_count_total=4,
        outcome_count_total=3,
        portfolio_verdict="AT_RISK",
        portfolio_score=25,
    )
    assert "risk" in out["headline"].lower()


def test_attention_count_overrides_verdict():
    """If needs_attention_count > 0, headline prioritises
    that over the portfolio verdict."""
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=3,
        portfolio_verdict="HEALTHY",
        portfolio_score=80,
        needs_attention_count=2,
    )
    assert "2" in out["headline"]
    assert "attention" in out["headline"].lower()


def test_insights_mention_counts():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=3,
        sim_count_total=10,
        decision_count_total=4,
        outcome_count_total=3,
    )
    n = out["narrative"].lower()
    assert "3 project" in n
    assert "10 sim" in n
    assert "4 decision" in n
    assert "3 outcome" in n


def test_weekly_summary_in_narrative():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=2,
        weekly_sim_count=5,
        weekly_decision_count=1,
        weekly_outcome_count=2,
    )
    n = out["narrative"].lower()
    assert "last 7 days" in n
    assert "5 sim" in n
    assert "1 decision" in n
    assert "2 outcome" in n


def test_severity_watch_when_attention_count_above_0():
    from app.simulation.insights import (
        SIGNAL_WATCH,
        build_insights,
    )
    out = build_insights(needs_attention_count=2)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_critical_when_attention_count_above_2():
    from app.simulation.insights import (
        SIGNAL_CRITICAL,
        build_insights,
    )
    out = build_insights(needs_attention_count=3)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_severity_ok_when_no_attention():
    from app.simulation.insights import (
        SIGNAL_OK,
        build_insights,
    )
    out = build_insights(needs_attention_count=0)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_skips_weekly_when_zero():
    from app.simulation.insights import build_insights
    out = build_insights(weekly_sim_count=0)
    n = out["narrative"].lower()
    assert "last 7 days" not in n


def test_mentions_attention_in_narrative():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=2,
        needs_attention_count=1,
    )
    n = out["narrative"].lower()
    assert "1 project" in n
    assert "need attention" in n


def test_narrative_pipe_separated():
    from app.simulation.insights import build_insights
    out = build_insights(
        project_count=2,
        sim_count_total=5,
        decision_count_total=1,
        outcome_count_total=1,
        weekly_sim_count=1,
    )
    # Multiple insights are pipe-separated.
    assert "|" in out["narrative"]


def test_schema_default_shape():
    from app.schemas.user import InsightsOut
    out = InsightsOut()
    assert out.has_data is False
    assert out.headline == ""
    assert out.insights == []
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import InsightsOut
    from app.simulation.insights import build_insights
    payload = build_insights(
        project_count=2,
        sim_count_total=5,
    )
    out = InsightsOut(**payload)
    assert out.has_data is True
    assert out.headline != ""
