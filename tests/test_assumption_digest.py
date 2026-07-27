"""Tests for the per-project assumption digest helper +
schema + route registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy + a
razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import assumption_digest

    assert set(assumption_digest.__all__) == {
        "MAX_WEAK_LINKS",
        "MAX_RECENT_ASSUMPTIONS",
        "MAX_KEY_SIGNALS",
        "SPECIFICITY_WEAK_THRESHOLD",
        "HIGH_SENSITIVITIES",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_assumption_digest",
    }


# ---------------------------------------------------------------------------
# Empty + minimal
# ---------------------------------------------------------------------------


def test_digest_empty_returns_zero_state() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([])
    assert out["assumption_count"] == 0
    assert out["sensitivity_breakdown"] == {}
    assert out["weak_link_count"] == 0
    assert out["weak_links"] == []
    assert "no assumptions" in out["narrative"].lower()


def test_digest_filters_hidden() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "visible", "sensitivity": "MEDIUM",
            "impact_score": 5.0, "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": 2, "text": "hidden", "sensitivity": "MEDIUM",
            "impact_score": 5.0, "is_hidden": True,
            "created_at": "2026-01-02T00:00:00Z",
        },
    ])
    assert out["assumption_count"] == 1


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------


def test_digest_sensitivity_breakdown() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {"id": 1, "text": "a", "sensitivity": "HIGH",
         "impact_score": 7.0, "is_hidden": False,
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "text": "b", "sensitivity": "HIGH",
         "impact_score": 6.0, "is_hidden": False,
         "created_at": "2026-01-02T00:00:00Z"},
        {"id": 3, "text": "c", "sensitivity": "LOW",
         "impact_score": 2.0, "is_hidden": False,
         "created_at": "2026-01-03T00:00:00Z"},
    ])
    assert out["sensitivity_breakdown"] == {"HIGH": 2, "LOW": 1}


def test_digest_category_breakdown() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {"id": 1, "text": "a", "sensitivity": "MEDIUM",
         "category": "pricing", "impact_score": 5.0,
         "is_hidden": False, "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "text": "b", "sensitivity": "MEDIUM",
         "category": "trust", "impact_score": 5.0,
         "is_hidden": False, "created_at": "2026-01-02T00:00:00Z"},
        {"id": 3, "text": "c", "sensitivity": "MEDIUM",
         "category": "pricing", "impact_score": 5.0,
         "is_hidden": False, "created_at": "2026-01-03T00:00:00Z"},
    ])
    assert out["category_breakdown"] == {"pricing": 2, "trust": 1}


# ---------------------------------------------------------------------------
# Weak-link detection
# ---------------------------------------------------------------------------


def test_digest_weak_link_high_sensitivity_low_specificity() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1,
            "text": "Vague but high-impact claim",
            "sensitivity": "HIGH",
            "category": "pricing",
            "impact_score": 8.0,
            "specificity_score": 0.2,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert out["weak_link_count"] == 1
    assert out["weak_links"][0]["text"] == "Vague but high-impact claim"
    assert out["weak_links"][0]["sensitivity"] == "HIGH"


def test_digest_no_weak_link_when_specificity_high() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "specific claim",
            "sensitivity": "HIGH", "category": "pricing",
            "impact_score": 8.0, "specificity_score": 0.9,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert out["weak_link_count"] == 0


def test_digest_no_weak_link_when_sensitivity_low() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "vague but low-impact",
            "sensitivity": "LOW", "category": "pricing",
            "impact_score": 1.0, "specificity_score": 0.2,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert out["weak_link_count"] == 0


def test_digest_weak_links_sorted_critical_first() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "high sensitivity",
            "sensitivity": "HIGH", "category": "x",
            "impact_score": 5.0, "specificity_score": 0.2,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": 2, "text": "critical sensitivity",
            "sensitivity": "CRITICAL", "category": "x",
            "impact_score": 5.0, "specificity_score": 0.2,
            "is_hidden": False,
            "created_at": "2026-01-02T00:00:00Z",
        },
    ])
    assert out["weak_links"][0]["id"] == 2  # CRITICAL wins


def test_digest_weak_links_capped() -> None:
    from app.simulation.assumption_digest import (
        MAX_WEAK_LINKS,
        build_assumption_digest,
    )

    assumptions = [
        {
            "id": i, "text": f"a{i}", "sensitivity": "HIGH",
            "category": "x", "impact_score": 5.0 - i * 0.01,
            "specificity_score": 0.2, "is_hidden": False,
            "created_at": f"2026-01-{i:02d}T00:00:00Z",
        }
        for i in range(1, 20)
    ]
    out = build_assumption_digest(assumptions)
    assert len(out["weak_links"]) == MAX_WEAK_LINKS


# ---------------------------------------------------------------------------
# Recent additions
# ---------------------------------------------------------------------------


def test_digest_recent_assumptions_newest_first() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {"id": 1, "text": "old", "sensitivity": "MEDIUM",
         "impact_score": 5.0, "is_hidden": False,
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 3, "text": "newest", "sensitivity": "MEDIUM",
         "impact_score": 5.0, "is_hidden": False,
         "created_at": "2026-01-03T00:00:00Z"},
        {"id": 2, "text": "middle", "sensitivity": "MEDIUM",
         "impact_score": 5.0, "is_hidden": False,
         "created_at": "2026-01-02T00:00:00Z"},
    ])
    assert [a["id"] for a in out["recent_assumptions"]] == [3, 2, 1]


def test_digest_handles_datetime_objects() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "x", "sensitivity": "MEDIUM",
            "impact_score": 5.0, "is_hidden": False,
            "created_at": datetime(
                2026, 1, 1, tzinfo=timezone.utc,
            ),
        },
    ])
    assert out["recent_assumptions"][0]["created_at"].startswith(
        "2026-01-01"
    )


def test_digest_handles_non_dict_entries() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        "not-a-dict",
        None,
        {"id": 1, "text": "ok", "sensitivity": "MEDIUM",
         "impact_score": 5.0, "is_hidden": False,
         "created_at": "2026-01-01T00:00:00Z"},
    ])
    assert out["assumption_count"] == 1


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_digest_narrative_mentions_weakest_link() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {
            "id": 1, "text": "Need to be cheaper",
            "sensitivity": "CRITICAL", "category": "pricing",
            "impact_score": 9.0, "specificity_score": 0.1,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert "Need to be cheaper" in out["narrative"]


def test_digest_narrative_includes_avg_impact() -> None:
    from app.simulation.assumption_digest import build_assumption_digest

    out = build_assumption_digest([
        {"id": 1, "text": "a", "sensitivity": "MEDIUM",
         "impact_score": 6.0, "is_hidden": False,
         "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "text": "b", "sensitivity": "MEDIUM",
         "impact_score": 4.0, "is_hidden": False,
         "created_at": "2026-01-02T00:00:00Z"},
    ])
    assert "5.0" in out["narrative"]


# ---------------------------------------------------------------------------
# Key signals
# ---------------------------------------------------------------------------


def test_digest_key_signals_weak_link_severity() -> None:
    """1-2 weak links → watch; >= 3 → critical."""
    from app.simulation.assumption_digest import (
        SIGNAL_CRITICAL,
        SIGNAL_WATCH,
        build_assumption_digest,
    )

    def make(i):
        return {
            "id": i, "text": f"a{i}", "sensitivity": "HIGH",
            "category": "x", "impact_score": 5.0,
            "specificity_score": 0.2, "is_hidden": False,
            "created_at": f"2026-01-{i:02d}T00:00:00Z",
        }

    out1 = build_assumption_digest([make(1)])
    sig = next(
        s for s in out1["key_signals"]
        if s["label"] == "weak_link_count"
    )
    assert sig["severity"] == SIGNAL_WATCH

    out3 = build_assumption_digest([make(i) for i in range(1, 4)])
    sig = next(
        s for s in out3["key_signals"]
        if s["label"] == "weak_link_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_default_specificity_is_middle() -> None:
    """When specificity_score is not provided, default to
    0.5 — under the WEAK threshold so it counts as a weak
    link only when sensitivity is HIGH/CRITICAL."""
    from app.simulation.assumption_digest import build_assumption_digest

    # Default specificity (0.5) + MEDIUM sensitivity → NOT
    # flagged (sensitivity is below threshold).
    out = build_assumption_digest([
        {
            "id": 1, "text": "a", "sensitivity": "MEDIUM",
            "impact_score": 5.0, "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert out["weak_link_count"] == 0

    # Default specificity (0.5) + HIGH sensitivity →
    # still NOT flagged (0.5 is at threshold).
    out2 = build_assumption_digest([
        {
            "id": 1, "text": "a", "sensitivity": "HIGH",
            "impact_score": 5.0, "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    assert out2["weak_link_count"] == 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_assumption_digest_out_default_shape() -> None:
    from app.schemas.assumption import AssumptionDigestOut

    out = AssumptionDigestOut()
    assert out.assumption_count == 0
    assert out.weak_links == []
    assert out.recent_assumptions == []


def test_assumption_digest_out_round_trips_helper_payload() -> None:
    from app.schemas.assumption import AssumptionDigestOut
    from app.simulation.assumption_digest import build_assumption_digest

    payload = build_assumption_digest([
        {
            "id": 1, "text": "x", "sensitivity": "MEDIUM",
            "category": "pricing", "impact_score": 5.0,
            "is_hidden": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    out = AssumptionDigestOut(**payload)
    assert out.assumption_count == 1
    assert out.category_breakdown == {"pricing": 1}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_assumption_digest_route_registered() -> None:
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
    assert (
        "/projects/{project_id}/assumption-digest" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/assumption-digest"
        ]
    )