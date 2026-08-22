"""Unit tests for the pure evidence-staleness builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.simulation.evidence_staleness import (
    FRESHNESS_AGING,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    build_evidence_staleness,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _assumption(
    assumption_id: int,
    *,
    text: str = "Users will pay",
    sensitivity: str = "HIGH",
) -> dict:
    return {
        "id": assumption_id,
        "text": text,
        "category": "Pricing",
        "sensitivity": sensitivity,
    }


def _evidence(assumption_id: int, age_days: float) -> dict:
    return {
        "assumption_id": assumption_id,
        "created_at": NOW - timedelta(days=age_days),
    }


def test_freshness_tiers_follow_age_boundaries() -> None:
    payload = build_evidence_staleness(
        [
            _assumption(1),
            _assumption(2, sensitivity="LOW"),
            _assumption(3, sensitivity="LOW"),
        ],
        [
            _evidence(1, age_days=5),
            _evidence(2, age_days=30),
            _evidence(3, age_days=90),
        ],
        project_id=10,
        now=NOW,
    )

    freshness_by_id = {
        row["assumption_id"]: row["freshness"] for row in payload["rows"]
    }
    assert freshness_by_id[1] == FRESHNESS_FRESH
    assert freshness_by_id[2] == FRESHNESS_AGING
    assert freshness_by_id[3] == FRESHNESS_STALE


def test_never_tested_leads_retest_queue_before_stale() -> None:
    payload = build_evidence_staleness(
        [
            _assumption(1, sensitivity="LOW"),
            _assumption(2),  # never tested, high sensitivity
            _assumption(3, sensitivity="LOW"),
        ],
        [_evidence(1, age_days=200), _evidence(3, age_days=100)],
        project_id=10,
        now=NOW,
    )

    order = [row["assumption_id"] for row in payload["rows"]]
    assert order[0] == 2  # never tested first despite equal sensitivity rank
    assert {order[1], order[2]} == {1, 3}

    summary = payload["summary"]
    assert summary["never_tested_count"] == 1
    assert summary["stale_count"] == 2
    assert summary["actionable_count"] == 3
    assert summary["oldest_days_since_evidence"] == 200.0


def test_unknown_when_timestamp_unparseable() -> None:
    payload = build_evidence_staleness(
        [_assumption(1)],
        [{"assumption_id": 1, "created_at": "not-a-date"}],
        project_id=10,
        now=NOW,
    )

    assert payload["rows"][0]["freshness"] == FRESHNESS_UNKNOWN
    assert payload["rows"][0]["evidence_count"] == 1
    # Unknown rows are excluded from the tested denominator.
    assert payload["summary"]["tested_assumptions"] == 0
    assert payload["summary"]["fresh_share_of_tested_pct"] is None


def test_recommendations_name_top_actionable_items() -> None:
    payload = build_evidence_staleness(
        [
            _assumption(1, text="Never checked", sensitivity="HIGH"),
            _assumption(2, text="Old news", sensitivity="MEDIUM"),
            _assumption(3, text="Fresh enough"),
        ],
        [
            _evidence(2, age_days=120),
            _evidence(3, age_days=2),
        ],
        project_id=10,
        now=NOW,
    )

    assert payload["recommendations"] == [
        'Design a first experiment for "Never checked" — it has never been '
        "tested.",
        'Re-test "Old news" — latest evidence is 120 days old.',
    ]


def test_empty_project_returns_zeroed_summary() -> None:
    payload = build_evidence_staleness([], [], project_id=10, now=NOW)

    assert payload["project_id"] == 10
    assert payload["rows"] == []
    assert payload["recommendations"] == []
    assert payload["summary"]["total_assumptions"] == 0
    assert payload["summary"]["actionable_count"] == 0
    assert payload["summary"]["stale_share_pct"] is None
    assert payload["meta"]["model"] == "evidence_staleness_v1"


def test_invalid_windows_are_rejected() -> None:
    with pytest.raises(ValueError):
        build_evidence_staleness(
            [], [], project_id=10, now=NOW, fresh_days=0, aging_days=45
        )
    with pytest.raises(ValueError):
        build_evidence_staleness(
            [], [], project_id=10, now=NOW, fresh_days=45, aging_days=45
        )


def test_naive_now_is_treated_as_utc() -> None:
    payload = build_evidence_staleness(
        [_assumption(1)],
        [_evidence(1, age_days=2)],
        project_id=10,
        now=datetime(2026, 8, 23),
    )

    assert payload["rows"][0]["freshness"] == FRESHNESS_FRESH
