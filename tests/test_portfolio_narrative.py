"""
Tests for the portfolio narrative helper + schema + route
registration.

The narrative logic is pure-Python so we can exercise it
without spinning up Postgres. The DB-touching route is
smoke-tested via the route-registration pattern (gated by
scipy).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import portfolio_narrative

    assert set(portfolio_narrative.__all__) == {
        "MAX_RECOMMENDED_ACTIONS",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "VALID_SIGNAL_SEVERITIES",
        "build_portfolio_narrative",
    }


def test_signal_severity_allowlist_pinned() -> None:
    from app.simulation.portfolio_narrative import (
        VALID_SIGNAL_SEVERITIES,
    )

    assert set(VALID_SIGNAL_SEVERITIES) == {
        "ok",
        "watch",
        "critical",
    }


# ---------------------------------------------------------------------------
# build_portfolio_narrative — empty / missing data
# ---------------------------------------------------------------------------


def test_narrative_all_none_returns_empty_payload() -> None:
    """All four sub-payloads missing → empty narrative + empty
    signals + empty actions (canonical shape)."""
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(None, None, None, None)
    assert out["narrative"] == ""
    assert out["key_signals"] == []
    assert out["recommended_actions"] == []


def test_narrative_handles_empty_dicts() -> None:
    """Empty dicts (not None) → narrative stays empty, but
    key_signals still carries the canonical sim-count + health
    pair for the dashboard to render."""
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative({}, {}, {}, {})
    # Empty inputs still produce a helpful explanatory
    # narrative (not a silent empty string).
    assert "empty" in out["narrative"].lower()
    # Sim count 0 + INSUFFICIENT_DATA → always produce the
    # canonical signals (mae is skipped because the value is
    # None, but sim-count + overall-health are present).
    signal_labels = {s["label"] for s in out["key_signals"]}
    assert "overall_health" in signal_labels
    assert "simulation_count" in signal_labels
    assert out["recommended_actions"] == []


# ---------------------------------------------------------------------------
# Narrative composition
# ---------------------------------------------------------------------------


def test_narrative_opens_with_sim_count_and_health() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "WELL_CALIBRATED",
            "mean_abs_variance": 0.015,
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    assert "5 simulation(s)" in out["narrative"]
    assert "WELL_CALIBRATED" in out["narrative"]


def test_narrative_empty_batch_message() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 0},
        calibration_health={},
        architect_leaderboard={},
        outlier_detection={},
    )
    assert "No simulations" in out["narrative"]


def test_narrative_includes_trajectory_text() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "WELL_CALIBRATED",
            "mean_abs_variance": 0.015,
            "health_trajectory": "IMPROVING",
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    assert "trending up" in out["narrative"]


def test_narrative_includes_streak_when_present() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 10},
        calibration_health={
            "overall_health": "WELL_CALIBRATED",
            "mean_abs_variance": 0.01,
            "consecutive_well_calibrated_days": 7,
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    assert "7-day well-calibrated streak" in out["narrative"]


def test_narrative_includes_top_architect() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "NEEDS_ATTENTION",
            "mean_abs_variance": 0.04,
            "top_miscalibrated_architect": {
                "architect_name": "PricingArchitect",
                "recommendation": "TIGHTEN",
            },
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    assert "PricingArchitect" in out["narrative"]
    assert "TIGHTEN" in out["narrative"]


def test_narrative_includes_outliers_singular() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "NEEDS_ATTENTION",
            "mean_abs_variance": 0.04,
        },
        architect_leaderboard={},
        outlier_detection={
            "outlier_count": 1,
            "outliers": [
                {"sim_id": 42, "z_score": 4.2},
            ],
        },
    )
    assert "1 outlier sim flagged" in out["narrative"]
    assert "42" in out["narrative"]


def test_narrative_includes_outliers_plural() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 10},
        calibration_health={"overall_health": "NEEDS_ATTENTION"},
        architect_leaderboard={},
        outlier_detection={"outlier_count": 3},
    )
    assert "3 outlier sims flagged" in out["narrative"]


# ---------------------------------------------------------------------------
# Key signals
# ---------------------------------------------------------------------------


def test_narrative_key_signals_mae_severity_ok() -> None:
    """MAE < 0.02 → ok severity."""
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
        SIGNAL_OK,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "WELL_CALIBRATED",
            "mean_abs_variance": 0.015,
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    mae_signal = next(
        s for s in out["key_signals"] if s["label"] == "mae"
    )
    assert mae_signal["severity"] == SIGNAL_OK
    assert mae_signal["value"] == 0.015


def test_narrative_key_signals_mae_severity_critical() -> None:
    """MAE ≥ 0.05 → critical severity."""
    from app.simulation.portfolio_narrative import (
        SIGNAL_CRITICAL,
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "POORLY_CALIBRATED",
            "mean_abs_variance": 0.08,
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    mae_signal = next(
        s for s in out["key_signals"] if s["label"] == "mae"
    )
    assert mae_signal["severity"] == SIGNAL_CRITICAL


def test_narrative_key_signals_overall_health_mapped() -> None:
    """Each overall_health label maps to a severity bucket."""
    from app.simulation.portfolio_narrative import (
        SIGNAL_OK,
        SIGNAL_WATCH,
        SIGNAL_CRITICAL,
        build_portfolio_narrative,
    )

    cases = [
        ("WELL_CALIBRATED", SIGNAL_OK),
        ("NEEDS_ATTENTION", SIGNAL_WATCH),
        ("POORLY_CALIBRATED", SIGNAL_CRITICAL),
    ]
    for health, expected_sev in cases:
        out = build_portfolio_narrative(
            portfolio_summary={"simulation_count": 5},
            calibration_health={"overall_health": health},
            architect_leaderboard={},
            outlier_detection={},
        )
        h_signal = next(
            s for s in out["key_signals"]
            if s["label"] == "overall_health"
        )
        assert h_signal["severity"] == expected_sev


def test_narrative_key_signals_includes_outlier_count() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 10},
        calibration_health={"overall_health": "WELL_CALIBRATED"},
        architect_leaderboard={},
        outlier_detection={"outlier_count": 2},
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "outlier_count"
    )
    assert sig["value"] == 2


# ---------------------------------------------------------------------------
# Recommended actions
# ---------------------------------------------------------------------------


def test_narrative_recommended_actions_from_leaderboard() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={"overall_health": "NEEDS_ATTENTION"},
        architect_leaderboard={
            "leaderboard": [
                {
                    "architect_name": "PricingArchitect",
                    "recommendation": "TIGHTEN",
                    "score": 0.5,
                    "priority_label": "HIGH",
                },
                {
                    "architect_name": "TrustArchitect",
                    "recommendation": "TRUSTED",
                    "score": 0.0,
                    "priority_label": "NONE",
                },
            ],
        },
        outlier_detection={},
    )
    actions = out["recommended_actions"]
    assert len(actions) == 1  # TRUSTED filtered out
    assert actions[0]["architect"] == "PricingArchitect"
    assert actions[0]["action"] == "TIGHTEN"


def test_narrative_recommended_actions_from_outliers() -> None:
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={"overall_health": "NEEDS_ATTENTION"},
        architect_leaderboard={"leaderboard": []},
        outlier_detection={
            "outliers": [
                {"sim_id": 42, "z_score": 4.2,
                 "deviation_severity": "MODERATE"},
            ],
        },
    )
    actions = out["recommended_actions"]
    assert len(actions) == 1
    assert actions[0]["architect"] is None
    assert "sim 42" in actions[0]["action"]


def test_narrative_recommended_actions_capped() -> None:
    """Hard cap prevents the dashboard tile from spamming."""
    from app.simulation.portfolio_narrative import (
        MAX_RECOMMENDED_ACTIONS,
        build_portfolio_narrative,
    )

    entries = [
        {
            "architect_name": f"a{i}",
            "recommendation": "TIGHTEN",
            "score": 0.5 - i * 0.01,
            "priority_label": "HIGH",
        }
        for i in range(20)
    ]
    out = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={"overall_health": "NEEDS_ATTENTION"},
        architect_leaderboard={"leaderboard": entries},
        outlier_detection={},
    )
    assert len(out["recommended_actions"]) == MAX_RECOMMENDED_ACTIONS


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_portfolio_narrative_out_default_shape() -> None:
    from app.schemas.simulation import PortfolioNarrativeOut

    out = PortfolioNarrativeOut()
    assert out.narrative == ""
    assert out.key_signals == []
    assert out.recommended_actions == []


def test_portfolio_narrative_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_portfolio_narrative(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import PortfolioNarrativeOut
    from app.simulation.portfolio_narrative import (
        build_portfolio_narrative,
    )

    payload = build_portfolio_narrative(
        portfolio_summary={"simulation_count": 5},
        calibration_health={
            "overall_health": "WELL_CALIBRATED",
            "mean_abs_variance": 0.015,
        },
        architect_leaderboard={},
        outlier_detection={},
    )
    out = PortfolioNarrativeOut(**payload)
    assert out.narrative != ""
    assert isinstance(out.key_signals, list)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_portfolio_narrative_route_registered() -> None:
    """GET /simulations/portfolio-narrative must appear in the
    router."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/portfolio-narrative" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/portfolio-narrative"]
    )


def test_portfolio_narrative_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is
    documented."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if (
            r.path == "/simulations/portfolio-narrative"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/portfolio-narrative route not found"
    )
