"""Tests for the per-project decision digest helper +
schema + route registration.

The digest logic is pure-Python so it can be exercised
without a DB. The route-registration check is gated by
scipy + a razorpay stub (same pattern as the other
simulation-route tests).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import decision_digest

    assert set(decision_digest.__all__) == {
        "MAX_TOP_DECISIONS",
        "MAX_PENDING_DECISIONS",
        "MAX_KEY_SIGNALS",
        "CLEAR_WIN_MARGIN",
        "PENDING_STATUSES",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_decision_digest",
    }


# ---------------------------------------------------------------------------
# Empty / minimal input
# ---------------------------------------------------------------------------


def test_digest_empty_list_returns_zero_state() -> None:
    from app.simulation.decision_digest import build_decision_digest

    out = build_decision_digest([])
    assert out["decision_count"] == 0
    assert out["status_breakdown"] == {}
    assert out["success_rate"] == 0.0
    assert out["pending_decisions"] == []
    assert out["top_decisions"] == []
    assert "empty" in out["narrative"].lower()


# ---------------------------------------------------------------------------
# Status breakdown
# ---------------------------------------------------------------------------


def test_digest_status_breakdown_counts() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "a", "status": "PENDING",
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "title": "b", "status": "PENDING",
         "created_at": "2026-01-02T00:00:00Z"},
        {"id": 3, "title": "c", "status": "RUNNING",
         "created_at": "2026-01-03T00:00:00Z"},
        {"id": 4, "title": "d", "status": "COMPLETED",
         "created_at": "2026-01-04T00:00:00Z",
         "results_json": {"winner_margin": 0.05,
                          "recommended_scenario": "X"}},
        {"id": 5, "title": "e", "status": "FAILED",
         "created_at": "2026-01-05T00:00:00Z"},
    ]
    out = build_decision_digest(decisions)
    assert out["status_breakdown"] == {
        "PENDING": 2, "RUNNING": 1, "COMPLETED": 1, "FAILED": 1,
    }


# ---------------------------------------------------------------------------
# Pending decisions — sorted oldest first, capped
# ---------------------------------------------------------------------------


def test_digest_pending_decisions_oldest_first() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 3, "title": "newer", "status": "PENDING",
         "created_at": "2026-01-03T00:00:00Z"},
        {"id": 1, "title": "older", "status": "PENDING",
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "title": "middle", "status": "PENDING",
         "created_at": "2026-01-02T00:00:00Z"},
    ]
    out = build_decision_digest(decisions)
    assert [d["id"] for d in out["pending_decisions"]] == [1, 2, 3]


def test_digest_pending_capped() -> None:
    from app.simulation.decision_digest import (
        MAX_PENDING_DECISIONS,
        build_decision_digest,
    )

    decisions = [
        {
            "id": i,
            "title": f"d{i}",
            "status": "PENDING",
            "created_at": f"2026-01-{i:02d}T00:00:00Z",
        }
        for i in range(1, 25)
    ]
    out = build_decision_digest(decisions)
    assert (
        len(out["pending_decisions"]) == MAX_PENDING_DECISIONS
    )


def test_digest_running_also_appears_in_pending() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "running", "status": "RUNNING",
         "created_at": "2026-01-01T00:00:00Z"},
    ]
    out = build_decision_digest(decisions)
    assert len(out["pending_decisions"]) == 1
    assert out["pending_decisions"][0]["status"] == "RUNNING"


# ---------------------------------------------------------------------------
# Top decisions — sorted by winner margin DESC, capped
# ---------------------------------------------------------------------------


def test_digest_top_decisions_by_margin_desc() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "small", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.01,
                          "recommended_scenario": "A"}},
        {"id": 2, "title": "big", "status": "COMPLETED",
         "created_at": "2026-01-02T00:00:00Z",
         "results_json": {"winner_margin": 0.12,
                          "recommended_scenario": "B"}},
        {"id": 3, "title": "mid", "status": "COMPLETED",
         "created_at": "2026-01-03T00:00:00Z",
         "results_json": {"winner_margin": 0.05,
                          "recommended_scenario": "C"}},
    ]
    out = build_decision_digest(decisions)
    assert [d["id"] for d in out["top_decisions"]] == [2, 3, 1]


def test_digest_top_decisions_capped() -> None:
    from app.simulation.decision_digest import (
        MAX_TOP_DECISIONS,
        build_decision_digest,
    )

    decisions = [
        {
            "id": i,
            "title": f"d{i}",
            "status": "COMPLETED",
            "created_at": f"2026-01-{i:02d}T00:00:00Z",
            "results_json": {
                "winner_margin": 0.1 - i * 0.005,
                "recommended_scenario": f"S{i}",
            },
        }
        for i in range(1, 15)
    ]
    out = build_decision_digest(decisions)
    assert len(out["top_decisions"]) == MAX_TOP_DECISIONS


# ---------------------------------------------------------------------------
# Success rate / winner margin
# ---------------------------------------------------------------------------


def test_digest_success_rate_counts_clear_winners() -> None:
    """A 'clear win' is a margin >= CLEAR_WIN_MARGIN (0.02)."""
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "ok", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.05,
                          "recommended_scenario": "X"}},
        {"id": 2, "title": "marginal", "status": "COMPLETED",
         "created_at": "2026-01-02T00:00:00Z",
         "results_json": {"winner_margin": 0.01,
                          "recommended_scenario": "Y"}},
        {"id": 3, "title": "another", "status": "COMPLETED",
         "created_at": "2026-01-03T00:00:00Z",
         "results_json": {"winner_margin": 0.10,
                          "recommended_scenario": "Z"}},
    ]
    out = build_decision_digest(decisions)
    # 2 of 3 (id 1, id 3) clear winners → 0.6667
    assert abs(out["success_rate"] - 2 / 3) < 1e-6


def test_digest_success_rate_zero_when_no_completed() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "pending", "status": "PENDING",
         "created_at": "2026-01-01T00:00:00Z"},
    ]
    out = build_decision_digest(decisions)
    assert out["success_rate"] == 0.0


def test_digest_avg_winner_margin() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "a", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.10,
                          "recommended_scenario": "A"}},
        {"id": 2, "title": "b", "status": "COMPLETED",
         "created_at": "2026-01-02T00:00:00Z",
         "results_json": {"winner_margin": 0.20,
                          "recommended_scenario": "B"}},
    ]
    out = build_decision_digest(decisions)
    assert abs(out["avg_winner_margin"] - 0.15) < 1e-6


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_digest_narrative_mentions_pending_when_present() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "Review pricing",
         "status": "PENDING",
         "created_at": "2026-01-01T00:00:00Z"},
    ]
    out = build_decision_digest(decisions)
    assert "Review pricing" in out["narrative"]


def test_digest_narrative_mentions_top_recommendation() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "decision", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.10,
                          "recommended_scenario": "Aggressive pricing"}},
    ]
    out = build_decision_digest(decisions)
    assert "Aggressive pricing" in out["narrative"]


def test_digest_narrative_calls_out_no_clear_winners() -> None:
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "a", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.005,
                          "recommended_scenario": "X"}},
    ]
    out = build_decision_digest(decisions)
    assert "no clear winner" in out["narrative"].lower()


# ---------------------------------------------------------------------------
# Key signals
# ---------------------------------------------------------------------------


def test_digest_key_signals_pending_severity() -> None:
    """0 pending → ok; 1-4 → watch; ≥5 → critical."""
    from app.simulation.decision_digest import (
        SIGNAL_CRITICAL,
        SIGNAL_OK,
        SIGNAL_WATCH,
        build_decision_digest,
    )

    # 0
    out = build_decision_digest([])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "pending_count"
    )
    assert sig["value"] == 0
    assert sig["severity"] == SIGNAL_OK

    # 1-4
    out = build_decision_digest([
        {"id": i, "title": f"p{i}", "status": "PENDING",
         "created_at": f"2026-01-{i:02d}T00:00:00Z"}
        for i in range(1, 4)
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "pending_count"
    )
    assert sig["value"] == 3
    assert sig["severity"] == SIGNAL_WATCH

    # ≥5
    out = build_decision_digest([
        {"id": i, "title": f"p{i}", "status": "PENDING",
         "created_at": f"2026-01-{i:02d}T00:00:00Z"}
        for i in range(1, 8)
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "pending_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_key_signals_failed_count() -> None:
    from app.simulation.decision_digest import (
        SIGNAL_CRITICAL,
        SIGNAL_WATCH,
        build_decision_digest,
    )

    out = build_decision_digest([
        {"id": 1, "title": "f", "status": "FAILED",
         "created_at": "2026-01-01T00:00:00Z"},
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "failed_count"
    )
    assert sig["value"] == 1
    assert sig["severity"] == SIGNAL_WATCH

    out = build_decision_digest([
        {"id": 1, "title": "f1", "status": "FAILED",
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "title": "f2", "status": "FAILED",
         "created_at": "2026-01-02T00:00:00Z"},
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "failed_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_handles_missing_results_json() -> None:
    """Some decisions have status=COMPLETED but no
    results_json (e.g. legacy rows). Must not crash."""
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {"id": 1, "title": "legacy", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": None},
    ]
    out = build_decision_digest(decisions)
    assert out["decision_count"] == 1
    # The top_decisions entry is still emitted (with 0.0
    # margin) so the dashboard sees the count.
    assert len(out["top_decisions"]) == 1
    assert out["top_decisions"][0]["winner_margin"] == 0.0


def test_digest_handles_datetime_objects() -> None:
    """Route layer passes datetime objects from SQLAlchemy;
    the helper must normalise them to strings."""
    from app.simulation.decision_digest import build_decision_digest

    decisions = [
        {
            "id": 1,
            "title": "x",
            "status": "PENDING",
            "created_at": datetime(
                2026, 1, 1, tzinfo=timezone.utc,
            ),
        },
    ]
    out = build_decision_digest(decisions)
    assert out["pending_decisions"][0]["created_at"].startswith(
        "2026-01-01"
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_decision_digest_out_default_shape() -> None:
    from app.schemas.decision import DecisionDigestOut

    out = DecisionDigestOut()
    assert out.decision_count == 0
    assert out.pending_decisions == []
    assert out.top_decisions == []
    assert out.key_signals == []
    assert out.narrative == ""


def test_decision_digest_out_round_trips_helper_payload() -> None:
    from app.schemas.decision import DecisionDigestOut
    from app.simulation.decision_digest import build_decision_digest

    payload = build_decision_digest([
        {"id": 1, "title": "t", "status": "COMPLETED",
         "created_at": "2026-01-01T00:00:00Z",
         "results_json": {"winner_margin": 0.05,
                          "recommended_scenario": "X"}},
    ])
    out = DecisionDigestOut(**payload)
    assert out.decision_count == 1
    assert out.top_decisions[0]["recommended_scenario"] == "X"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_decision_digest_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import decisions as dec_mod

    paths = {r.path for r in dec_mod.router.routes}
    assert (
        "/projects/{project_id}/decision-digest" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for r in dec_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/decision-digest"
        ]
    )