"""Tests for the per-user digest-snapshot helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

from datetime import datetime, timezone



def test_public_allowlist_matches_callers() -> None:
    from app.simulation import digest_snapshot

    assert set(digest_snapshot.__all__) == {
        "build_digest_snapshot",
    }


def test_snapshot_all_none_returns_empty() -> None:
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(None, None, None, None, None)
    assert out["snapshot_at"] != ""
    assert out["schema_version"] == 1
    assert out["dashboard"] == {}
    assert out["account_health"] == {}
    assert out["coverage_gaps"] == {}
    assert out["notifications"] == {}
    assert out["weekly_digest"] == {}


def test_snapshot_with_data_passes_through() -> None:
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(
        dashboard={"tier": "PRO"},
        account_health={"health_score": 85},
        coverage_gaps={"missing_categories": []},
        notifications={"count": 3},
        weekly_digest={"sim_count_week": 5},
    )
    assert out["dashboard"]["tier"] == "PRO"
    assert out["account_health"]["health_score"] == 85
    assert out["coverage_gaps"]["missing_categories"] == []
    assert out["notifications"]["count"] == 3
    assert out["weekly_digest"]["sim_count_week"] == 5


def test_snapshot_timestamp_uses_now() -> None:
    """When no `now` override is supplied, snapshot_at
    defaults to a non-empty ISO string."""
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(None, None, None, None, None)
    # Should be a parseable ISO timestamp.
    parsed = datetime.fromisoformat(out["snapshot_at"])
    assert isinstance(parsed, datetime)


def test_snapshot_timestamp_uses_override() -> None:
    from app.simulation.digest_snapshot import build_digest_snapshot

    fixed = datetime(2026, 1, 5, 10, 30, 0, tzinfo=timezone.utc)
    out = build_digest_snapshot(
        None, None, None, None, None, now=fixed,
    )
    assert out["snapshot_at"] == "2026-01-05T10:30:00+00:00"


def test_snapshot_partial_input_keeps_others_empty() -> None:
    """When only some sources supplied, missing ones
    default to empty dicts so the schema stays stable."""
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(
        dashboard={"tier": "PRO"},
        account_health=None,
        coverage_gaps=None,
        notifications=None,
        weekly_digest=None,
    )
    assert out["dashboard"] == {"tier": "PRO"}
    assert out["account_health"] == {}
    assert out["coverage_gaps"] == {}
    assert out["notifications"] == {}
    assert out["weekly_digest"] == {}


def test_snapshot_schema_default_shape() -> None:
    from app.schemas.user import DigestSnapshotOut

    out = DigestSnapshotOut()
    assert out.snapshot_at == ""
    assert out.schema_version == 1
    assert out.dashboard == {}
    assert out.account_health == {}
    assert out.coverage_gaps == {}
    assert out.notifications == {}
    assert out.weekly_digest == {}


def test_snapshot_schema_round_trips_helper_payload() -> None:
    from app.schemas.user import DigestSnapshotOut
    from app.simulation.digest_snapshot import build_digest_snapshot

    payload = build_digest_snapshot(
        dashboard={"tier": "PRO"},
        account_health={"score": 80},
        coverage_gaps={},
        notifications={},
        weekly_digest={},
    )
    out = DigestSnapshotOut(**payload)
    assert out.dashboard["tier"] == "PRO"
    assert out.account_health["score"] == 80


def test_snapshot_schema_version_field() -> None:
    """schema_version=1 is locked — bumping requires an
    explicit migration in any consumer that stored a
    snapshot."""
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(None, None, None, None, None)
    assert out["schema_version"] == 1


def test_snapshot_empty_dicts_pass_through_unmodified() -> None:
    """Pre-populated empty dicts stay empty."""
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot({}, {}, {}, {}, {})
    assert out["dashboard"] == {}
    assert out["account_health"] == {}
    assert out["coverage_gaps"] == {}
    assert out["notifications"] == {}
    assert out["weekly_digest"] == {}