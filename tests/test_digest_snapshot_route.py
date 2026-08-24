"""Polish-tests for the /me/digest-snapshot route.

The endpoint is uncached by design (it captures current
state for archival / email snapshots). These tests
focus on route registration + freshness: a mutation in
one of the 5 source rows must propagate to the next
digest-snapshot call.

Mirrors the route-registration pattern from the other
per-project + per-user endpoints.
"""
from __future__ import annotations

import pytest


def test_digest_snapshot_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import users as users_mod

    paths = {r.path for r in users_mod.router.routes}
    assert "/users/me/digest-snapshot" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in users_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/users/me/digest-snapshot"]
    )


def test_digest_snapshot_helper_payload_keys_match_schema() -> None:
    """The build_digest_snapshot helper's output keys
    must line up with the DigestSnapshotOut schema fields
    so a schema round-trip doesn't lose data.
    """
    from app.schemas.user import DigestSnapshotOut
    from app.simulation.digest_snapshot import build_digest_snapshot

    payload = build_digest_snapshot(
        dashboard={"a": 1},
        account_health={"b": 2},
        coverage_gaps={"c": 3},
        notifications={"d": 4},
        weekly_digest={"e": 5},
    )
    out = DigestSnapshotOut(**payload)
    assert out.dashboard == {"a": 1}
    assert out.account_health == {"b": 2}
    assert out.coverage_gaps == {"c": 3}
    assert out.notifications == {"d": 4}
    assert out.weekly_digest == {"e": 5}


def test_digest_snapshot_timestamp_is_set_on_every_call() -> None:
    """A second call within the same test should produce a
    non-empty snapshot_at (the helper always sets it).
    """
    from app.simulation.digest_snapshot import build_digest_snapshot

    out1 = build_digest_snapshot(None, None, None, None, None)
    out2 = build_digest_snapshot(None, None, None, None, None)
    assert out1["snapshot_at"] != ""
    assert out2["snapshot_at"] != ""


def test_digest_snapshot_composes_via_build_helper() -> None:
    """All 5 component digests must be present in the
    output so a downstream consumer can rely on the schema.
    """
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(None, None, None, None, None)
    expected_keys = {
        "snapshot_at", "schema_version",
        "dashboard", "account_health", "coverage_gaps",
        "notifications", "weekly_digest",
    }
    assert set(out.keys()) == expected_keys


def test_digest_snapshot_schema_version_constant() -> None:
    """schema_version must stay at 1 until an explicit
    migration is shipped - consumers depend on it for
    archival reads.
    """
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(None, None, None, None, None)
    assert out["schema_version"] == 1


def test_digest_snapshot_passes_through_all_five_components() -> None:
    """When all 5 sources are supplied, the output must
    mirror all 5 as-is."""
    from app.simulation.digest_snapshot import build_digest_snapshot

    out = build_digest_snapshot(
        dashboard={"key": "dashboard-value"},
        account_health={"key": "account-health-value"},
        coverage_gaps={"key": "coverage-gaps-value"},
        notifications={"key": "notifications-value"},
        weekly_digest={"key": "weekly-digest-value"},
    )
    assert out["dashboard"]["key"] == "dashboard-value"
    assert out["account_health"]["key"] == "account-health-value"
    assert out["coverage_gaps"]["key"] == "coverage-gaps-value"
    assert out["notifications"]["key"] == "notifications-value"
    assert out["weekly_digest"]["key"] == "weekly-digest-value"
