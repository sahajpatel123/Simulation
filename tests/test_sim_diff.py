"""
Tests for the sim-comparison helper + schema + route
registration.

The diff logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested
via the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import sim_diff

    assert set(sim_diff.__all__) == {
        "build_sim_diff",
    }


# ---------------------------------------------------------------------------
# build_sim_diff — empty / missing data
# ---------------------------------------------------------------------------


def test_sim_diff_with_no_data_returns_empty_payload() -> None:
    """Two None sims → empty (but well-formed) payload."""
    from app.simulation.sim_diff import build_sim_diff

    out = build_sim_diff(1, None, 2, None)
    assert out["sim_a_meta"]["sim_id"] == 1
    assert out["sim_b_meta"]["sim_id"] == 2
    # Counts are zero when findings is None.
    assert out["findings_diff"]["sim_a_total_count"] == 0
    assert out["findings_diff"]["sim_b_total_count"] == 0
    # Predicted/actual are None when missing.
    assert out["conversion_diff"]["sim_a"]["predicted_conversion"] is None
    assert out["conversion_diff"]["sim_b"]["predicted_conversion"] is None


# ---------------------------------------------------------------------------
# Meta echo
# ---------------------------------------------------------------------------


def test_sim_diff_echoes_metadata() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {
        "project_id": 10,
        "status": "COMPLETED",
        "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "predicted_conversion_rate": 0.10,
        "actual_conversion_rate": 0.08,
        "domain_findings": [],
    }
    out = build_sim_diff(101, a, 202, None)
    meta = out["sim_a_meta"]
    assert meta["sim_id"] == 101
    assert meta["project_id"] == 10
    assert meta["status"] == "COMPLETED"
    assert meta["predicted_conversion_rate"] == pytest.approx(0.10)
    assert meta["actual_conversion_rate"] == pytest.approx(0.08)
    assert meta["created_at"].startswith("2026-01-15")


# ---------------------------------------------------------------------------
# findings_diff
# ---------------------------------------------------------------------------


def _finding(severity: str) -> dict:
    return {
        "architect_name": "PricingArchitect",
        "severity": severity,
    }


def test_sim_diff_counts_findings_by_severity() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [_finding("CRITICAL")] * 3
         + [_finding("WARNING")] * 2}
    b = {"domain_findings": [_finding("CRITICAL")]
         + [_finding("INFO")] * 4}
    out = build_sim_diff(1, a, 2, b)
    assert out["findings_diff"]["sim_a"]["CRITICAL"] == 3
    assert out["findings_diff"]["sim_a"]["WARNING"] == 2
    assert out["findings_diff"]["sim_a"]["INFO"] == 0
    assert out["findings_diff"]["sim_b"]["CRITICAL"] == 1
    assert out["findings_diff"]["sim_b"]["WARNING"] == 0
    assert out["findings_diff"]["sim_b"]["INFO"] == 4
    assert out["findings_diff"]["sim_a_total_count"] == 5
    assert out["findings_diff"]["sim_b_total_count"] == 5


def test_sim_diff_findings_winner_per_severity() -> None:
    """Each severity has its own winner."""
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [_finding("CRITICAL")] * 3}
    b = {"domain_findings": [_finding("CRITICAL")] * 1}
    out = build_sim_diff(1, a, 2, b)
    assert out["findings_diff"]["critical_count_winner"] == "SIM_A"


def test_sim_diff_findings_total_winner() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [_finding("INFO")] * 5}
    b = {"domain_findings": [_finding("INFO")] * 2}
    out = build_sim_diff(1, a, 2, b)
    assert out["findings_diff"]["total_count_winner"] == "SIM_A"


def test_sim_diff_findings_tie() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [_finding("CRITICAL")] * 2}
    b = {"domain_findings": [_finding("CRITICAL")] * 2}
    out = build_sim_diff(1, a, 2, b)
    assert out["findings_diff"]["critical_count_winner"] == "TIE"


def test_sim_diff_skips_non_dict_findings() -> None:
    """A bad entry in the findings list is skipped, not crashed."""
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [
        _finding("CRITICAL"),
        "not a dict",
        _finding("WARNING"),
    ]}
    out = build_sim_diff(1, a, 2, None)
    # 2 valid findings counted (CRITICAL + WARNING).
    assert out["findings_diff"]["sim_a_total_count"] == 2


def test_sim_diff_skips_unknown_severity_into_info() -> None:
    """A finding with severity='FOO' is counted as INFO
    (defensive fallback so unknown severities don't drop)."""
    from app.simulation.sim_diff import build_sim_diff

    a = {"domain_findings": [
        {"architect_name": "x", "severity": "FOO"},
        _finding("CRITICAL"),
    ]}
    out = build_sim_diff(1, a, 2, None)
    assert out["findings_diff"]["sim_a"]["INFO"] == 1
    assert out["findings_diff"]["sim_a"]["CRITICAL"] == 1


# ---------------------------------------------------------------------------
# conversion_diff
# ---------------------------------------------------------------------------


def test_sim_diff_conversion_deltas() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {"predicted_conversion_rate": 0.10, "actual_conversion_rate": 0.08}
    b = {"predicted_conversion_rate": 0.15, "actual_conversion_rate": 0.12}
    out = build_sim_diff(1, a, 2, b)
    cd = out["conversion_diff"]
    assert cd["sim_a"]["predicted_conversion"] == pytest.approx(0.10)
    assert cd["sim_b"]["predicted_conversion"] == pytest.approx(0.15)
    # predicted_delta = SIM_A − SIM_B = -0.05
    assert cd["predicted_delta"] == pytest.approx(-0.05)
    # actual_delta = 0.08 − 0.12 = -0.04
    assert cd["actual_delta"] == pytest.approx(-0.04)
    # variance = pred − actual → 0.02 vs 0.03
    assert cd["sim_a"]["variance"] == pytest.approx(0.02)
    assert cd["sim_b"]["variance"] == pytest.approx(0.03)
    # variance_delta = 0.02 − 0.03 = -0.01
    assert cd["variance_delta"] == pytest.approx(-0.01)


def test_sim_diff_variance_winner_picks_smaller_abs() -> None:
    """Winner is the side with the smaller |variance|."""
    from app.simulation.sim_diff import build_sim_diff

    a = {"predicted_conversion_rate": 0.10, "actual_conversion_rate": 0.05}  # |0.05|
    b = {"predicted_conversion_rate": 0.20, "actual_conversion_rate": 0.05}  # |0.15|
    out = build_sim_diff(1, a, 2, b)
    # SIM_A has smaller |variance| → wins.
    assert out["conversion_diff"]["variance_winner"] == "SIM_A"


def test_sim_diff_conversion_deltas_none_when_missing() -> None:
    """A side with missing predicted/actual has None deltas."""
    from app.simulation.sim_diff import build_sim_diff

    a = {"predicted_conversion_rate": None, "actual_conversion_rate": None}
    b = {"predicted_conversion_rate": 0.10, "actual_conversion_rate": 0.08}
    out = build_sim_diff(1, a, 2, b)
    assert out["conversion_diff"]["predicted_delta"] is None
    assert out["conversion_diff"]["actual_delta"] is None
    assert out["conversion_diff"]["variance_delta"] is None


# ---------------------------------------------------------------------------
# aggregate_diff
# ---------------------------------------------------------------------------


def test_sim_diff_aggregate_diff_has_four_metric_rows() -> None:
    from app.simulation.sim_diff import build_sim_diff

    out = build_sim_diff(1, None, 2, None)
    rows = out["aggregate_diff"]
    assert len(rows) == 4
    metrics = [r["metric"] for r in rows]
    assert "predicted_conversion_rate" in metrics
    assert "actual_conversion_rate" in metrics
    assert "variance" in metrics
    assert "total_finding_count" in metrics


def test_sim_diff_aggregate_diff_winners_carried() -> None:
    from app.simulation.sim_diff import build_sim_diff

    a = {
        "predicted_conversion_rate": 0.20,
        "actual_conversion_rate": 0.18,
        "domain_findings": [_finding("INFO")] * 5,
    }
    b = {
        "predicted_conversion_rate": 0.10,
        "actual_conversion_rate": 0.08,
        "domain_findings": [_finding("INFO")] * 2,
    }
    out = build_sim_diff(1, a, 2, b)
    rows = {r["metric"]: r for r in out["aggregate_diff"]}
    assert rows["predicted_conversion_rate"]["winner"] == "SIM_A"
    assert rows["actual_conversion_rate"]["winner"] == "SIM_A"
    assert rows["total_finding_count"]["winner"] == "SIM_A"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_sim_diff_summary_includes_both_sides() -> None:
    from app.simulation.sim_diff import build_sim_diff

    out = build_sim_diff(
        101, {"domain_findings": [_finding("INFO")] * 3},
        202, {"domain_findings": [_finding("INFO")] * 1},
    )
    assert "101" in out["summary"]
    assert "202" in out["summary"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_sim_diff_out_default_shape() -> None:
    from app.schemas.simulation import SimDiffOut

    out = SimDiffOut()
    assert out.sim_a_meta == {}
    assert out.sim_b_meta == {}
    assert out.findings_diff == {}
    assert out.conversion_diff == {}
    assert out.aggregate_diff == []
    assert out.summary == ""


def test_sim_diff_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_sim_diff(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import SimDiffOut
    from app.simulation.sim_diff import build_sim_diff

    payload = build_sim_diff(
        101,
        {"predicted_conversion_rate": 0.10,
         "actual_conversion_rate": 0.08},
        202,
        {"predicted_conversion_rate": 0.12,
         "actual_conversion_rate": 0.10},
    )
    out = SimDiffOut(**payload)
    assert out.sim_a_meta["sim_id"] == 101
    assert out.sim_b_meta["sim_id"] == 202


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_sim_diff_route_registered() -> None:
    """GET /simulations/sim-diff must appear in the router."""
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
    assert "/simulations/sim-diff" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/sim-diff"]


def test_sim_diff_route_query_params() -> None:
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
            r.path == "/simulations/sim-diff"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "sim_a" in query_param_names
            assert "sim_b" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/sim-diff route not found"
    )