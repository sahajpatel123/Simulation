"""Tests for the per-project intervention digest helper +
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
    from app.simulation import intervention_digest

    assert set(intervention_digest.__all__) == {
        "MAX_TOP",
        "MAX_KEY_SIGNALS",
        "STALE_AFTER_DAYS",
        "QUICK_WIN_DIFFICULTY",
        "QUICK_WIN_MIN_PRIORITY",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_intervention_digest",
    }


# ---------------------------------------------------------------------------
# Empty / missing input
# ---------------------------------------------------------------------------


def test_digest_none_returns_empty_state() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest(None)
    assert out["intervention_count"] == 0
    assert out["quick_win_count"] == 0
    assert out["top_interventions"] == []
    assert out["stale"] is True


def test_digest_missing_interventions_list() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({"generated_at": "2026-01-01T00:00:00Z"})
    assert out["intervention_count"] == 0


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------


def test_digest_difficulty_breakdown() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "a", "difficulty": "LOW",
             "priority_score": 0.5, "category": "pricing"},
            {"id": 2, "title": "b", "difficulty": "HIGH",
             "priority_score": 0.7, "category": "trust"},
            {"id": 3, "title": "c", "difficulty": "LOW",
             "priority_score": 0.9, "category": "pricing"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["difficulty_breakdown"] == {"LOW": 2, "HIGH": 1}


def test_digest_priority_breakdown() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "a", "priority": "HIGH",
             "priority_score": 0.5, "difficulty": "LOW"},
            {"id": 2, "title": "b", "priority": "MEDIUM",
             "priority_score": 0.5, "difficulty": "LOW"},
            {"id": 3, "title": "c", "priority": "HIGH",
             "priority_score": 0.5, "difficulty": "LOW"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["priority_breakdown"] == {"HIGH": 2, "MEDIUM": 1}


def test_digest_category_breakdown() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "a", "category": "pricing",
             "priority_score": 0.5, "difficulty": "LOW"},
            {"id": 2, "title": "b", "category": "trust",
             "priority_score": 0.5, "difficulty": "LOW"},
            {"id": 3, "title": "c", "category": "pricing",
             "priority_score": 0.5, "difficulty": "LOW"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["category_breakdown"] == {"pricing": 2, "trust": 1}


# ---------------------------------------------------------------------------
# Quick win detection
# ---------------------------------------------------------------------------


def test_digest_quick_wins_low_difficulty_high_priority() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "low+high", "difficulty": "LOW",
             "priority_score": 0.95, "category": "x"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["quick_win_count"] == 1


def test_digest_no_quick_win_when_priority_at_threshold() -> None:
    """Score > 0.70 required (strict greater-than)."""
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "borderline", "difficulty": "LOW",
             "priority_score": 0.70, "category": "x"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["quick_win_count"] == 0


def test_digest_no_quick_win_when_high_difficulty() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "hard", "difficulty": "HIGH",
             "priority_score": 0.95, "category": "x"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["quick_win_count"] == 0


# ---------------------------------------------------------------------------
# Top interventions
# ---------------------------------------------------------------------------


def test_digest_top_interventions_sorted_by_score_desc() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "low", "priority_score": 0.3,
             "difficulty": "LOW"},
            {"id": 2, "title": "high", "priority_score": 0.95,
             "difficulty": "LOW"},
            {"id": 3, "title": "mid", "priority_score": 0.6,
             "difficulty": "LOW"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert [t["id"] for t in out["top_interventions"]] == [2, 3, 1]


def test_digest_top_interventions_capped() -> None:
    from app.simulation.intervention_digest import (
        MAX_TOP,
        build_intervention_digest,
    )

    out = build_intervention_digest({
        "interventions": [
            {
                "id": i, "title": f"i{i}",
                "priority_score": 1.0 - i * 0.01,
                "difficulty": "LOW",
            }
            for i in range(1, 20)
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert len(out["top_interventions"]) == MAX_TOP


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_digest_stale_when_old() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    # Generated 20 days ago, "now" is today.
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_intervention_digest(
        {
            "interventions": [
                {"id": 1, "title": "x", "difficulty": "LOW",
                 "priority_score": 0.9},
            ],
            "generated_at": "2026-05-12T00:00:00+00:00",
        },
        now=now,
    )
    assert out["stale"] is True


def test_digest_fresh_when_recent() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_intervention_digest(
        {
            "interventions": [
                {"id": 1, "title": "x", "difficulty": "LOW",
                 "priority_score": 0.9},
            ],
            "generated_at": "2026-05-25T00:00:00+00:00",
        },
        now=now,
    )
    assert out["stale"] is False


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_digest_handles_non_dict_entries() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            "not-a-dict",
            None,
            {"id": 1, "title": "ok", "difficulty": "LOW",
             "priority_score": 0.5, "category": "x"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert out["intervention_count"] == 1


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_digest_narrative_mentions_top_recommendation() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    out = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "Cut the price 20%",
             "difficulty": "LOW",
             "priority_score": 0.95, "category": "pricing"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    assert "Cut the price 20%" in out["narrative"]


def test_digest_narrative_mentions_stale_when_old() -> None:
    from app.simulation.intervention_digest import build_intervention_digest

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = build_intervention_digest(
        {
            "interventions": [
                {"id": 1, "title": "x", "difficulty": "LOW",
                 "priority_score": 0.9},
            ],
            "generated_at": "2025-12-01T00:00:00+00:00",
        },
        now=now,
    )
    assert "stale" in out["narrative"].lower()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_intervention_digest_out_default_shape() -> None:
    from app.schemas.project import InterventionDigestOut

    out = InterventionDigestOut()
    assert out.intervention_count == 0
    assert out.quick_win_count == 0
    assert out.top_interventions == []
    assert out.stale is True


def test_intervention_digest_out_round_trips_helper_payload() -> None:
    from app.schemas.project import InterventionDigestOut
    from app.simulation.intervention_digest import (
        build_intervention_digest,
    )

    payload = build_intervention_digest({
        "interventions": [
            {"id": 1, "title": "x", "difficulty": "LOW",
             "priority_score": 0.5, "category": "pricing"},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
    })
    out = InterventionDigestOut(**payload)
    assert out.intervention_count == 1
    assert out.category_breakdown == {"pricing": 1}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_intervention_digest_route_registered() -> None:
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
        "/projects/{project_id}/intervention-digest" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/intervention-digest"
        ]
    )