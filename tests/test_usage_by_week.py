"""Tests for the per-user usage-by-week helper."""
from __future__ import annotations

from datetime import date


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import usage_by_week

    assert set(usage_by_week.__all__) == {
        "MAX_WEEKS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_usage_by_week",
    }


def test_usage_empty_returns_zero_state() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([])
    assert out["week_count"] == 0
    assert out["weeks"] == []


def test_usage_passes_through_per_week_fields() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {
            "week_start": "2026-01-05",
            "sim_count": 3,
            "decision_count": 1,
            "outcome_count": 2,
        },
    ])
    w = out["weeks"][0]
    assert w["week_start"] == "2026-01-05"
    assert w["sim_count"] == 3


def test_usage_aggregates_totals() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {"week_start": "2026-01-05",
         "sim_count": 2, "decision_count": 1, "outcome_count": 1},
        {"week_start": "2026-01-12",
         "sim_count": 3, "decision_count": 2, "outcome_count": 1},
    ])
    assert out["sim_total"] == 5
    assert out["decision_total"] == 3
    assert out["outcome_total"] == 2


def test_usage_capped_at_max_weeks() -> None:
    from app.simulation.usage_by_week import (
        MAX_WEEKS,
        build_usage_by_week,
    )

    weeks = [
        {
            "week_start": f"2026-{(i % 28) + 1:02d}",
            "sim_count": 1, "decision_count": 0,
            "outcome_count": 0,
        }
        for i in range(MAX_WEEKS + 5)
    ]
    out = build_usage_by_week(weeks)
    assert len(out["weeks"]) == MAX_WEEKS


def test_usage_handles_datetime_objects_in_week_start() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {
            "week_start": date(2026, 1, 5),
            "sim_count": 0, "decision_count": 0,
            "outcome_count": 0,
        },
    ])
    assert out["weeks"][0]["week_start"] == "2026-01-05"


def test_usage_handles_non_dict_entries() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        "not-a-dict",
        None,
        {"week_start": "2026-01-05",
         "sim_count": 0, "decision_count": 0,
         "outcome_count": 0},
    ])
    assert out["week_count"] == 1


def test_usage_narrative_mentions_latest_week() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {"week_start": "2026-01-05",
         "sim_count": 1, "decision_count": 1,
         "outcome_count": 1},
    ])
    assert "Latest week (2026-01-05)" in out["narrative"]


def test_usage_key_signal_weekly_delta_when_2_weeks() -> None:
    """weekly_sim_delta signal present only when 2+ weeks
    of data."""
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {"week_start": "2026-01-05",
         "sim_count": 1, "decision_count": 0,
         "outcome_count": 0},
        {"week_start": "2026-01-12",
         "sim_count": 4, "decision_count": 0,
         "outcome_count": 0},
    ])
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "weekly_sim_delta"
    )
    assert sig["value"] == 3
    assert "+3" in sig["display"]


def test_usage_no_delta_signal_when_only_one_week() -> None:
    from app.simulation.usage_by_week import build_usage_by_week

    out = build_usage_by_week([
        {"week_start": "2026-01-05",
         "sim_count": 5, "decision_count": 0,
         "outcome_count": 0},
    ])
    labels = {s["label"] for s in out["key_signals"]}
    assert "weekly_sim_delta" not in labels


def test_usage_schema_default_shape() -> None:
    from app.schemas.user import UsageByWeekOut

    out = UsageByWeekOut()
    assert out.week_count == 0
    assert out.weeks == []
    assert out.sim_total == 0


def test_usage_schema_round_trip() -> None:
    from app.schemas.user import UsageByWeekOut
    from app.simulation.usage_by_week import build_usage_by_week

    payload = build_usage_by_week([
        {"week_start": "2026-01-05",
         "sim_count": 5, "decision_count": 1,
         "outcome_count": 1},
    ])
    out = UsageByWeekOut(**payload)
    assert out.week_count == 1
    assert out.weeks[0]["sim_count"] == 5
