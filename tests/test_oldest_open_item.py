"""Tests for the per-user oldest-open-item helper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone



def test_public_allowlist_matches_callers():
    from app.simulation import oldest_open_item
    assert set(oldest_open_item.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_oldest_open_item",
    }


def test_default_empty_state():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    out = build_oldest_open_item()
    assert out["oldest_age_days"] is None
    assert out["oldest_type"] is None
    assert out["oldest_project_id"] is None
    assert out["key_signals"] == []


def test_picks_oldest():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (now - timedelta(days=5), "sim", 1),
            (now - timedelta(days=20), "decision", 2),
            (now - timedelta(days=1), "outcome", 3),
        ],
        now=now,
    )
    assert out["oldest_type"] == "decision"
    assert out["oldest_project_id"] == 2
    assert out["oldest_age_days"] == 20


def test_handles_naive_datetime():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (datetime(2026, 1, 1), "sim", 1),  # naive
        ],
        now=now,
    )
    # 2026-01-01 -> 2026-01-10 = 9 days
    assert out["oldest_age_days"] == 9


def test_handles_aware_datetime():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (
                datetime(2026, 1, 5, tzinfo=timezone.utc),
                "sim", 1,
            ),
        ],
        now=now,
    )
    assert out["oldest_age_days"] == 5


def test_skips_non_list_entries():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    out = build_oldest_open_item([
        "not-a-tuple",
        None,
        (datetime(2026, 1, 1, tzinfo=timezone.utc), "sim", 1),
    ])
    assert out["oldest_type"] == "sim"


def test_skips_short_entries():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    out = build_oldest_open_item([
        (datetime(2026, 1, 1, tzinfo=timezone.utc),),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), "sim", 1),
    ])
    assert out["oldest_type"] == "sim"


def test_severity_critical_above_30_days():
    from app.simulation.oldest_open_item import (
        SIGNAL_CRITICAL,
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (now - timedelta(days=45), "sim", 1),
        ],
        now=now,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_severity_watch_between_14_and_30_days():
    from app.simulation.oldest_open_item import (
        SIGNAL_WATCH,
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (now - timedelta(days=20), "sim", 1),
        ],
        now=now,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_severity_ok_below_14_days():
    from app.simulation.oldest_open_item import (
        SIGNAL_OK,
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (now - timedelta(days=5), "sim", 1),
        ],
        now=now,
    )
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_narrative_quiet_when_empty():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    out = build_oldest_open_item()
    assert "accumulate" in out["narrative"].lower()


def test_narrative_mentions_age_when_data():
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    out = build_oldest_open_item(
        [
            (now - timedelta(days=5), "sim", 1),
        ],
        now=now,
    )
    assert "5 day" in out["narrative"]
    assert "sim" in out["narrative"]


def test_schema_default_shape():
    from app.schemas.project import OldestOpenItemOut
    out = OldestOpenItemOut()
    assert out.oldest_age_days is None
    assert out.oldest_type is None
    assert out.oldest_project_id is None
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import OldestOpenItemOut
    from app.simulation.oldest_open_item import (
        build_oldest_open_item,
    )
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    payload = build_oldest_open_item(
        [
            (now - timedelta(days=5), "sim", 1),
        ],
        now=now,
    )
    out = OldestOpenItemOut(**payload)
    assert out.oldest_type == "sim"
    assert out.oldest_project_id == 1
