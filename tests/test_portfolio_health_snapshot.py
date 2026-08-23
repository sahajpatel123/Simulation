"""Tests for the per-user portfolio-health-snapshot helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers():
    from app.simulation import portfolio_health_snapshot
    assert set(portfolio_health_snapshot.__all__) == {
        "HEALTHY_MIN", "AT_RISK_MAX",
        "VERDICT_HEALTHY", "VERDICT_NEEDS_ATTENTION",
        "VERDICT_AT_RISK",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_portfolio_health_snapshot",
    }


def test_empty_returns_zero_state():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([])
    assert out["project_count"] == 0
    assert out["portfolio_health_score"] == 0
    assert out["lowest_project_score"] is None


def test_healthy_when_all_projects_high():
    from app.simulation.portfolio_health_snapshot import (
        VERDICT_HEALTHY,
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 90},
        {"project_health_score": 80},
    ])
    assert out["project_count"] == 2
    assert out["portfolio_health_score"] == 85
    assert out["verdict"] == VERDICT_HEALTHY
    assert out["lowest_project_score"] == 80


def test_at_risk_when_all_projects_low():
    from app.simulation.portfolio_health_snapshot import (
        VERDICT_AT_RISK,
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 20},
        {"project_health_score": 30},
    ])
    assert out["verdict"] == VERDICT_AT_RISK
    assert out["lowest_project_score"] == 20


def test_needs_attention_in_middle():
    from app.simulation.portfolio_health_snapshot import (
        VERDICT_NEEDS_ATTENTION,
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 50},
    ])
    assert out["verdict"] == VERDICT_NEEDS_ATTENTION
    assert out["portfolio_health_score"] == 50


def test_skips_zero_scores():
    """Zero scores are likely missing data - skip them."""
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 0},
        {"project_health_score": 90},
    ])
    assert out["project_count"] == 1
    assert out["portfolio_health_score"] == 90


def test_skips_non_dict_entries():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        "not-a-dict",
        None,
        {"project_health_score": 80},
    ])
    assert out["project_count"] == 1


def test_narrative_mentions_count_and_verdict():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 85},
    ])
    n = out["narrative"]
    assert "1 project" in n
    assert "85" in n
    assert "healthy" in n


def test_narrative_mentions_worst_when_below_50():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 90},
        {"project_health_score": 30},
    ])
    assert "30" in out["narrative"]


def test_narrative_no_projects_message():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([])
    assert "No projects" in out["narrative"]


def test_key_signals_present():
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    out = build_portfolio_health_snapshot([
        {"project_health_score": 90},
    ])
    labels = {s["label"] for s in out["key_signals"]}
    assert "portfolio_health_score" in labels
    assert "project_count" in labels


def test_schema_default_shape():
    from app.schemas.user import PortfolioHealthSnapshotOut
    out = PortfolioHealthSnapshotOut()
    assert out.project_count == 0
    assert out.portfolio_health_score == 0
    assert out.verdict == "AT_RISK"
    assert out.lowest_project_score is None


def test_schema_round_trip():
    from app.schemas.user import PortfolioHealthSnapshotOut
    from app.simulation.portfolio_health_snapshot import (
        build_portfolio_health_snapshot,
    )
    payload = build_portfolio_health_snapshot([
        {"project_health_score": 90},
        {"project_health_score": 80},
    ])
    out = PortfolioHealthSnapshotOut(**payload)
    assert out.project_count == 2
    assert out.portfolio_health_score == 85
    assert out.verdict == "HEALTHY"
    assert out.lowest_project_score == 80
