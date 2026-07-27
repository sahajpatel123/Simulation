"""Tests for the next-best-action helper + schema +
route registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy +
a razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import next_best_action

    assert set(next_best_action.__all__) == {
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "CATEGORY_MISCALIBRATION",
        "CATEGORY_PENDING_DECISION",
        "CATEGORY_CALIBRATION_HEALTH",
        "CATEGORY_FIRST_SIM",
        "CATEGORY_NO_SIGNAL",
        "build_next_best_action",
    }


# ---------------------------------------------------------------------------
# Priority 1: top CRITICAL architect finding
# ---------------------------------------------------------------------------


def test_priority1_picks_top_critical_finding() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_MISCALIBRATION,
        SIGNAL_CRITICAL,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=[
            {
                "findings": [
                    {
                        "architect": "PricingArchitect",
                        "severity": "CRITICAL",
                        "recommendation": "TIGHTEN",
                        "title": "Pricing above willingness-to-pay",
                    },
                    {
                        "architect": "TrustArchitect",
                        "severity": "WARN",
                        "title": "Lower trust in Tier-3",
                    },
                ],
            },
        ],
        pending_decisions=None,
        calibration_health=None,
        has_any_simulation=True,
    )
    assert out["category"] == CATEGORY_MISCALIBRATION
    assert out["severity"] == SIGNAL_CRITICAL
    assert out["action"] == "TIGHTEN PricingArchitect"
    assert out["title"] == "Pricing above willingness-to-pay"
    assert out["fallback"] is False


def test_priority1_skips_non_critical_findings() -> None:
    """A sim full of WARN / INFO findings must NOT trigger
    the miscalibration category."""
    from app.simulation.next_best_action import (
        CATEGORY_PENDING_DECISION,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=[
            {
                "findings": [
                    {
                        "architect": "PricingArchitect",
                        "severity": "WARN",
                        "title": "Pricing slightly high",
                    },
                ],
            },
        ],
        pending_decisions=[
            {"id": 7, "title": "Old decision", "status": "PENDING",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        calibration_health=None,
        has_any_simulation=True,
    )
    assert out["category"] == CATEGORY_PENDING_DECISION


def test_priority1_handles_missing_findings_list() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_PENDING_DECISION,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=[{}],  # no "findings" key
        pending_decisions=[
            {"id": 1, "title": "t", "status": "PENDING",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        calibration_health=None,
        has_any_simulation=True,
    )
    assert out["category"] == CATEGORY_PENDING_DECISION


# ---------------------------------------------------------------------------
# Priority 2: oldest pending decision
# ---------------------------------------------------------------------------


def test_priority2_oldest_pending_decision() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_PENDING_DECISION,
        SIGNAL_WATCH,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=None,
        pending_decisions=[
            {"id": 7, "title": "Should we try freemium?",
             "status": "PENDING",
             "created_at": "2026-01-04T00:00:00Z"},
            {"id": 5, "title": "Pivot to B2B?",
             "status": "PENDING",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        calibration_health=None,
        has_any_simulation=True,
    )
    # The OLDEST pending decision wins (id 5).
    assert out["category"] == CATEGORY_PENDING_DECISION
    assert out["severity"] == SIGNAL_WATCH
    assert out["action"] == "Review & decide"
    assert "Pivot to B2B?" in out["title"]
    assert out["source"]["ref_id"] == 5


# ---------------------------------------------------------------------------
# Priority 3: POORLY_CALIBRATED health verdict
# ---------------------------------------------------------------------------


def test_priority3_poorly_calibrated_triggers() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_CALIBRATION_HEALTH,
        SIGNAL_CRITICAL,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=None,
        pending_decisions=None,
        calibration_health={
            "overall_health": "POORLY_CALIBRATED",
            "mean_abs_variance": 0.07,
            "top_miscalibrated_architect": {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
            },
        },
        has_any_simulation=True,
    )
    assert out["category"] == CATEGORY_CALIBRATION_HEALTH
    assert out["severity"] == SIGNAL_CRITICAL
    assert out["action"] == "TIGHTEN PricingArchitect"


def test_priority3_skips_well_calibrated_health() -> None:
    """NEEDS_ATTENTION / WELL_CALIBRATED / INSUFFICIENT_DATA
    must NOT trigger the calibration-health category —
    they fall through to the empty-state."""
    from app.simulation.next_best_action import (
        CATEGORY_NO_SIGNAL,
        build_next_best_action,
    )

    for verdict in ("WELL_CALIBRATED", "NEEDS_ATTENTION",
                    "INSUFFICIENT_DATA"):
        out = build_next_best_action(
            latest_findings=None,
            pending_decisions=None,
            calibration_health={"overall_health": verdict},
            has_any_simulation=True,
        )
        assert out["category"] == CATEGORY_NO_SIGNAL


# ---------------------------------------------------------------------------
# Priority 4: brand-new project fallback
# ---------------------------------------------------------------------------


def test_priority4_first_sim_fallback_when_no_data() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_FIRST_SIM,
        SIGNAL_WATCH,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=None,
        pending_decisions=None,
        calibration_health=None,
        has_any_simulation=False,
    )
    assert out["category"] == CATEGORY_FIRST_SIM
    assert out["severity"] == SIGNAL_WATCH
    assert out["fallback"] is True
    assert "first simulation" in out["title"].lower()


# ---------------------------------------------------------------------------
# Empty-state fallback
# ---------------------------------------------------------------------------


def test_empty_state_all_clear() -> None:
    """A healthy project with nothing to act on gets an
    'All clear' nudge (still actionable: 'run another')."""
    from app.simulation.next_best_action import (
        CATEGORY_NO_SIGNAL,
        SIGNAL_OK,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=None,
        pending_decisions=None,
        calibration_health={"overall_health": "WELL_CALIBRATED"},
        has_any_simulation=True,
    )
    assert out["category"] == CATEGORY_NO_SIGNAL
    assert out["severity"] == SIGNAL_OK
    assert out["fallback"] is True


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_skips_non_dict_entries_in_findings() -> None:
    from app.simulation.next_best_action import (
        CATEGORY_FIRST_SIM,
        build_next_best_action,
    )

    out = build_next_best_action(
        latest_findings=[
            "not-a-dict",
            {"findings": ["also-not-a-dict", None]},
        ],
        pending_decisions=None,
        calibration_health=None,
        has_any_simulation=False,
    )
    assert out["category"] == CATEGORY_FIRST_SIM


def test_falls_through_action_chain_correctly() -> None:
    """Top-critical beats pending beats calibration beats
    fallback. Pin the precedence explicitly."""
    from app.simulation.next_best_action import (
        CATEGORY_MISCALIBRATION,
        build_next_best_action,
    )

    # Same inputs but vary one priority at a time.
    base = {
        "latest_findings": [
            {
                "findings": [
                    {
                        "architect": "PricingArchitect",
                        "severity": "CRITICAL",
                        "recommendation": "TIGHTEN",
                        "title": "Critical",
                    },
                ],
            },
        ],
        "pending_decisions": [
            {"id": 1, "title": "Pending", "status": "PENDING",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        "calibration_health": {
            "overall_health": "POORLY_CALIBRATED",
            "mean_abs_variance": 0.1,
            "top_miscalibrated_architect": {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
            },
        },
        "has_any_simulation": True,
    }
    assert (
        build_next_best_action(**base)["category"]
        == CATEGORY_MISCALIBRATION
    )

    # Drop the critical finding → pending wins.
    no_crit = {**base, "latest_findings": None}
    from app.simulation.next_best_action import (
        CATEGORY_PENDING_DECISION,
    )
    assert (
        build_next_best_action(**no_crit)["category"]
        == CATEGORY_PENDING_DECISION
    )

    # Drop both → calibration health wins.
    no_crit_no_pend = {**no_crit, "pending_decisions": None}
    from app.simulation.next_best_action import (
        CATEGORY_CALIBRATION_HEALTH,
    )
    assert (
        build_next_best_action(**no_crit_no_pend)["category"]
        == CATEGORY_CALIBRATION_HEALTH
    )

    # Drop everything → fallback.
    nothing = {
        "latest_findings": None,
        "pending_decisions": None,
        "calibration_health": None,
        "has_any_simulation": False,
    }
    from app.simulation.next_best_action import CATEGORY_FIRST_SIM
    assert (
        build_next_best_action(**nothing)["category"]
        == CATEGORY_FIRST_SIM
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_next_best_action_out_default_shape() -> None:
    from app.schemas.project import NextBestActionOut

    out = NextBestActionOut()
    assert out.title == ""
    assert out.action == ""
    assert out.reason == ""
    assert out.severity == "ok"
    assert out.category == "no_signal"
    assert out.fallback is True


def test_next_best_action_out_round_trips_helper_payload() -> None:
    from app.schemas.project import (
        NextBestActionOut,
        NextBestActionSource,
    )
    from app.simulation.next_best_action import (
        CATEGORY_MISCALIBRATION,
        build_next_best_action,
    )

    payload = build_next_best_action(
        latest_findings=[
            {
                "findings": [
                    {
                        "architect": "TrustArchitect",
                        "severity": "CRITICAL",
                        "recommendation": "INVESTIGATE_BIAS",
                        "title": "Trust scores inflated",
                    },
                ],
            },
        ],
        pending_decisions=None,
        calibration_health=None,
        has_any_simulation=True,
    )
    out = NextBestActionOut(
        title=payload["title"],
        action=payload["action"],
        reason=payload["reason"],
        severity=payload["severity"],
        category=payload["category"],
        source=NextBestActionSource(**payload["source"]),
        fallback=payload["fallback"],
    )
    assert out.category == CATEGORY_MISCALIBRATION
    assert out.action == "INVESTIGATE_BIAS TrustArchitect"
    assert out.source.kind == "architect_finding"
    assert out.source.ref_label == "TrustArchitect"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_next_action_route_registered() -> None:
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
    assert "/projects/{project_id}/next-action" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/projects/{project_id}/next-action"]
    )