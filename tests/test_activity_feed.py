"""Tests for the per-project activity feed helper + schema
+ route registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy + a
razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import activity_feed

    assert set(activity_feed.__all__) == {
        "MAX_EVENTS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_activity_feed",
    }


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_feed_empty_returns_empty_payload() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed()
    assert out["event_count"] == 0
    assert out["events"] == []
    assert out["key_signals"][0]["label"] == "event_count"


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------


def test_feed_sim_created_event_emitted() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[{
            "id": 1,
            "status": "PENDING",
            "created_at": "2026-01-01T00:00:00Z",
        }],
    )
    types = [e["type"] for e in out["events"]]
    assert "sim_created" in types
    created = next(
        e for e in out["events"] if e["type"] == "sim_created"
    )
    assert created["ref_id"] == 1
    assert created["severity"] == "watch"


def test_feed_sim_completed_event_emitted() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[{
            "id": 1,
            "status": "COMPLETED",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "results_json": {"mean_conversion_rate": 0.042},
        }],
    )
    types = [e["type"] for e in out["events"]]
    assert "sim_created" in types
    assert "sim_completed" in types
    completed = next(
        e for e in out["events"] if e["type"] == "sim_completed"
    )
    assert "4.20%" in completed["summary"]


def test_feed_sim_failed_event_emitted() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[{
            "id": 1,
            "status": "FAILED",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "error_message": "GPU worker died",
        }],
    )
    types = [e["type"] for e in out["events"]]
    assert "sim_failed" in types
    failed = next(
        e for e in out["events"] if e["type"] == "sim_failed"
    )
    assert failed["severity"] == "critical"
    assert "GPU worker died" in failed["summary"]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def test_feed_decision_created_event() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        decisions=[{
            "id": 1,
            "status": "PENDING",
            "title": "Pivot to B2B?",
            "created_at": "2026-01-01T00:00:00Z",
        }],
    )
    created = out["events"][0]
    assert created["type"] == "decision_created"
    assert "Pivot to B2B?" in created["title"]


def test_feed_decision_completed_event() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        decisions=[{
            "id": 1,
            "status": "COMPLETED",
            "title": "Pivot to B2B?",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "results_json": {
                "recommended_scenario": "B2B Enterprise",
                "winner_margin": 0.07,
            },
        }],
    )
    completed = next(
        e for e in out["events"]
        if e["type"] == "decision_completed"
    )
    assert completed["severity"] == "ok"
    assert "B2B Enterprise" in completed["summary"]
    assert "7.0%" in completed["summary"]


def test_feed_decision_failed_event() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        decisions=[{
            "id": 1,
            "status": "FAILED",
            "title": "Test decision",
            "created_at": "2026-01-01T00:00:00Z",
            "error_message": "Invalid scenario params",
        }],
    )
    failed = next(
        e for e in out["events"]
        if e["type"] == "decision_failed"
    )
    assert failed["severity"] == "critical"


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_feed_outcome_submitted_event() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        outcomes=[{
            "id": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "actual_conversion_rate": 0.052,
        }],
    )
    assert out["events"][0]["type"] == "outcome_submitted"
    assert "5.20%" in out["events"][0]["summary"]


# ---------------------------------------------------------------------------
# Sorting + cap
# ---------------------------------------------------------------------------


def test_feed_events_sorted_newest_first() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[
            {
                "id": 1, "status": "COMPLETED",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "results_json": {},
            },
            {
                "id": 2, "status": "PENDING",
                "created_at": "2026-01-05T00:00:00Z",
            },
        ],
    )
    timestamps = [
        e["occurred_at"] for e in out["events"][:4]
    ]
    # Sorted DESC.
    assert timestamps == sorted(timestamps, reverse=True)


def test_feed_capped_at_max_events() -> None:
    from app.simulation.activity_feed import (
        MAX_EVENTS,
        build_activity_feed,
    )

    sims = [
        {
            "id": i, "status": "PENDING",
            "created_at": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
        }
        for i in range(1, 100)
    ]
    out = build_activity_feed(sims=sims)
    assert len(out["events"]) == MAX_EVENTS
    # event_count still reflects the uncapped total.
    assert out["event_count"] == len(sims)


# ---------------------------------------------------------------------------
# Narrative + key signals
# ---------------------------------------------------------------------------


def test_feed_narrative_empty() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed()
    assert "empty" in out["narrative"].lower()


def test_feed_narrative_mentions_counts() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[
            {
                "id": 1, "status": "PENDING",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ],
        decisions=[
            {
                "id": 1, "status": "PENDING", "title": "x",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ],
        outcomes=[
            {
                "id": 1, "created_at": "2026-01-01T00:00:00Z",
                "actual_conversion_rate": 0.04,
            },
        ],
    )
    assert "simulation(s)" in out["narrative"]
    assert "decision(s)" in out["narrative"]
    assert "outcome(s)" in out["narrative"]


def test_feed_key_signals_recent_failures() -> None:
    from app.simulation.activity_feed import (
        SIGNAL_WATCH,
        build_activity_feed,
    )

    out = build_activity_feed(
        sims=[
            {
                "id": 1, "status": "FAILED",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "error_message": "boom",
            },
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "recent_failures"
    )
    assert sig["value"] == 1
    assert sig["severity"] == SIGNAL_WATCH


def test_feed_key_signals_failures_two_is_critical() -> None:
    from app.simulation.activity_feed import (
        SIGNAL_CRITICAL,
        build_activity_feed,
    )

    out = build_activity_feed(
        sims=[
            {
                "id": i, "status": "FAILED",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
            }
            for i in range(1, 3)
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "recent_failures"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_feed_handles_datetime_objects() -> None:
    """SQLAlchemy passes datetime instances; the helper
    must normalise them to strings."""
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[{
            "id": 1, "status": "PENDING",
            "created_at": datetime(
                2026, 1, 1, tzinfo=UTC,
            ),
        }],
    )
    assert out["events"][0]["occurred_at"].startswith("2026-01-01")


def test_feed_handles_non_dict_entries() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=["not-a-dict", None, {"id": 1, "status": "PENDING",
                                   "created_at": "2026-01-01T00:00:00Z"}],
    )
    # Only the valid entry contributes an event.
    assert len(out["events"]) == 1


def test_feed_handles_missing_results_json() -> None:
    from app.simulation.activity_feed import build_activity_feed

    out = build_activity_feed(
        sims=[{
            "id": 1, "status": "COMPLETED",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "results_json": None,
        }],
    )
    completed = next(
        e for e in out["events"]
        if e["type"] == "sim_completed"
    )
    assert completed["summary"] == "Completed"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_activity_feed_out_default_shape() -> None:
    from app.schemas.project import ActivityFeedOut

    out = ActivityFeedOut()
    assert out.event_count == 0
    assert out.events == []
    assert out.key_signals == []
    assert out.narrative == ""


def test_activity_feed_out_round_trips_helper_payload() -> None:
    from app.schemas.project import ActivityFeedOut
    from app.simulation.activity_feed import build_activity_feed

    payload = build_activity_feed(
        sims=[{
            "id": 1, "status": "COMPLETED",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "results_json": {"mean_conversion_rate": 0.04},
        }],
    )
    out = ActivityFeedOut(**payload)
    assert out.event_count == 2  # created + completed
    assert len(out.events) == 2  # created + completed


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_activity_feed_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import projects as proj_mod

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/activity-feed" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/activity-feed"
        ]
    )
