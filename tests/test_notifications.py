"""Tests for the per-user notifications helper + schema.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import notifications

    assert set(notifications.__all__) == {
        "MAX_NOTIFICATIONS",
        "NOTIFICATION_CRITICAL",
        "NOTIFICATION_WATCH",
        "NOTIFICATION_INFO",
        "build_notifications",
    }


def test_notifications_empty_returns_empty_payload() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications()
    assert out["notification_count"] == 0
    assert out["notifications"] == []
    assert "empty" in out["narrative"].lower()


def test_notifications_blindspot_critical() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        blindspots=[
            {
                "blindspot_type": "CLUSTER_IGNORED",
                "blindspot_value": "metro professionals",
                "occurrence_count": 5,
                "first_seen": "2026-01-01T00:00:00Z",
                "last_surfaced_to_user": None,
            },
        ],
    )
    assert out["notification_count"] == 1
    n = out["notifications"][0]
    assert n["category"] == "blindspot"
    assert n["severity"] == "critical"


def test_notifications_pending_decision_watch() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        pending_decisions=[
            {
                "id": 1, "title": "Pivot to B2B?",
                "status": "PENDING",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    assert out["notification_count"] == 1
    n = out["notifications"][0]
    assert n["category"] == "pending_decision"
    assert n["severity"] == "watch"
    assert n["ref_id"] == 1


def test_notifications_quickwin_critical() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        intervention_dicts=[
            {
                "id": 1,
                "title": "Cut the price 20%",
                "description": "...",
                "difficulty": "LOW",
                "priority_score": 0.95,
            },
        ],
    )
    assert out["notification_count"] == 1
    n = out["notifications"][0]
    assert n["category"] == "intervention_quickwin"
    assert n["severity"] == "critical"


def test_notifications_no_quickwin_when_difficulty_high() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        intervention_dicts=[
            {
                "id": 1,
                "title": "Hard intervention",
                "description": "...",
                "difficulty": "HIGH",
                "priority_score": 0.95,
            },
        ],
    )
    assert out["notification_count"] == 0


def test_notifications_premortem_critical_summary() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        recent_premortem_criticals=3,
    )
    assert out["notification_count"] == 1
    n = out["notifications"][0]
    assert n["category"] == "premortem_critical"
    assert n["severity"] == "critical"


def test_notifications_sorted_newest_first() -> None:
    from app.simulation.notifications import build_notifications

    now = datetime(2026, 1, 10, tzinfo=UTC)
    out = build_notifications(
        pending_decisions=[
            {
                "id": 1, "title": "old", "status": "PENDING",
                "created_at": now - timedelta(days=5),
            },
            {
                "id": 2, "title": "new", "status": "PENDING",
                "created_at": now - timedelta(hours=1),
            },
        ],
    )
    # The newer decision (id=2) should come first.
    assert out["notifications"][0]["ref_id"] == 2


def test_notifications_capped() -> None:
    from app.simulation.notifications import (
        MAX_NOTIFICATIONS,
        build_notifications,
    )

    pending_decisions = [
        {
            "id": i, "title": f"d{i}", "status": "PENDING",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        for i in range(50)
    ]
    out = build_notifications(pending_decisions=pending_decisions)
    assert len(out["notifications"]) == MAX_NOTIFICATIONS


def test_notifications_critical_signal_severity() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        blindspots=[
            {
                "blindspot_type": "x", "blindspot_value": "y",
                "occurrence_count": 3,
                "first_seen": None,
                "last_surfaced_to_user": None,
            },
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "notification_count"
    )
    assert sig["severity"] == "watch"


def test_notifications_critical_count_signal_when_many() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        blindspots=[
            {
                "blindspot_type": f"x{i}",
                "blindspot_value": "y",
                "occurrence_count": 3,
                "first_seen": None,
                "last_surfaced_to_user": None,
            }
            for i in range(3)
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "critical_notification_count"
    )
    assert sig["value"] == 3
    assert sig["severity"] == "critical"


def test_notifications_handles_non_dict_entries() -> None:
    from app.simulation.notifications import build_notifications

    out = build_notifications(
        blindspots=[
            "not-a-dict",
            None,
            {
                "blindspot_type": "x", "blindspot_value": "y",
                "occurrence_count": 3,
                "first_seen": None,
                "last_surfaced_to_user": None,
            },
        ],
    )
    assert out["notification_count"] == 1
