"""Tests for the per-user most-active-weekday helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import most_active_weekday
    assert set(most_active_weekday.__all__) == {
        "WEEKDAY_NAMES",
        "SIGNAL_OK", "SIGNAL_WATCH",
        "build_most_active_weekday",
    }


def test_default_empty_state():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday()
    assert out["total_actions"] == 0
    assert out["most_active_weekday"] is None
    assert out["most_active_count"] == 0
    assert out["key_signals"] == []


def test_picks_most_frequent_weekday():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday([
        0, 0, 0, 1, 2,  # 3x Monday, 1x Tue, 1x Wed
        4, 4,           # 2x Fri
    ])
    # Monday (0) is most frequent.
    assert out["most_active_weekday"] == 0
    assert out["most_active_count"] == 3
    assert out["total_actions"] == 7


def test_picks_first_on_tie():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday([2, 5])
    # max() returns the first key with the max count.
    # 2 (Wednesday) wins on the tie.
    assert out["most_active_weekday"] == 2


def test_skips_non_int_entries():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday([
        "not-an-int",
        None,
        2, 3,
    ])
    assert out["total_actions"] == 2


def test_skips_out_of_range_weekdays():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday([2, -1, 7, 3, 100])
    # Only 2 and 3 are valid 0-6 weekday ints.
    assert out["total_actions"] == 2


def test_severity_ok_when_high_count():
    from app.simulation.most_active_weekday import (
        SIGNAL_OK,
        build_most_active_weekday,
    )
    out = build_most_active_weekday([
        0, 0, 0, 0, 0,
    ])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_severity_watch_when_low_count():
    from app.simulation.most_active_weekday import (
        SIGNAL_WATCH,
        build_most_active_weekday,
    )
    out = build_most_active_weekday([0])
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_no_key_signal_when_empty():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday()
    assert out["key_signals"] == []


def test_narrative_quiet_when_empty():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday()
    assert "no" in out["narrative"].lower()


def test_narrative_includes_day_name_when_data():
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    out = build_most_active_weekday([0, 0, 1])
    # 0 is Monday.
    assert "Monday" in out["narrative"]
    assert "2" in out["narrative"]


def test_schema_default_shape():
    from app.schemas.project import MostActiveWeekdayOut
    out = MostActiveWeekdayOut()
    assert out.total_actions == 0
    assert out.most_active_weekday is None
    assert out.most_active_count == 0
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import MostActiveWeekdayOut
    from app.simulation.most_active_weekday import (
        build_most_active_weekday,
    )
    payload = build_most_active_weekday([0, 0, 0])
    out = MostActiveWeekdayOut(**payload)
    assert out.most_active_weekday == 0
    assert out.most_active_count == 3
