"""
Tests for the cross-simulation findings aggregate helper + schema +
route registration.

The aggregating logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# severity helpers
# ---------------------------------------------------------------------------


def test_normalise_severity_default_is_info() -> None:
    from app.simulation.findings_aggregate import normalise_severity

    assert normalise_severity(None) == "INFO"
    assert normalise_severity("") == "INFO"
    assert normalise_severity("  ") == "INFO"


def test_normalise_severity_uppercases() -> None:
    from app.simulation.findings_aggregate import normalise_severity

    assert normalise_severity("critical") == "CRITICAL"
    assert normalise_severity("  Warning  ") == "WARNING"


def test_normalise_severity_rejects_unknown() -> None:
    from app.simulation.findings_aggregate import normalise_severity

    with pytest.raises(ValueError):
        normalise_severity("crit")
    with pytest.raises(ValueError):
        normalise_severity("fatal")


def test_severity_meets_min_monotonic() -> None:
    from app.simulation.findings_aggregate import severity_meets_min

    # CRITICAL >= WARNING >= INFO
    assert severity_meets_min("CRITICAL", "INFO")
    assert severity_meets_min("CRITICAL", "WARNING")
    assert severity_meets_min("CRITICAL", "CRITICAL")
    assert severity_meets_min("WARNING", "INFO")
    assert severity_meets_min("WARNING", "WARNING")
    assert not severity_meets_min("WARNING", "CRITICAL")
    assert not severity_meets_min("INFO", "WARNING")
    assert severity_meets_min("INFO", "INFO")


# ---------------------------------------------------------------------------
# aggregate_findings — pure helper
# ---------------------------------------------------------------------------


def _finding(architect: str, severity: str, impact: float = 0.0) -> dict:
    return {
        "architect_name": architect,
        "severity": severity,
        "conversion_impact": impact,
    }


def _sims(*finding_lists: list[dict]) -> list[dict]:
    """Build a list of ``results_json`` payloads, one per simulation."""
    return [{"domain_findings": list(fl)} for fl in finding_lists]


def test_aggregate_empty_input_returns_zero_summary() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings([])
    assert out["total_findings"] == 0
    assert out["filtered_findings"] == 0
    assert out["severity_breakdown"] == {}
    assert out["by_architect"] == []
    assert out["top_architects"] == []
    assert out["simulation_count"] == 0
    assert out["simulations_with_findings"] == 0
    assert out["shared_domain_count"] == 0


def test_aggregate_counts_severities_across_sims() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings(
        _sims(
            [_finding("pricing", "CRITICAL"), _finding("pricing", "WARNING")],
            [_finding("pricing", "CRITICAL"), _finding("trust", "INFO")],
        )
    )
    assert out["total_findings"] == 4
    assert out["severity_breakdown"] == {
        "CRITICAL": 2,
        "WARNING": 1,
        "INFO": 1,
    }
    assert out["simulation_count"] == 2
    assert out["simulations_with_findings"] == 2


def test_aggregate_filters_by_min_severity() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings(
        _sims(
            [_finding("pricing", "CRITICAL"), _finding("pricing", "WARNING")],
        ),
        min_severity="CRITICAL",
    )
    # Total counts every finding; filtered counts only CRITICAL.
    assert out["total_findings"] == 2
    assert out["filtered_findings"] == 1
    # by_architect is computed against the filtered slice.
    assert len(out["by_architect"]) == 1
    assert out["by_architect"][0]["architect_name"] == "pricing"
    assert out["by_architect"][0]["critical_count"] == 1


def test_aggregate_groups_by_architect() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings(
        _sims(
            [
                _finding("pricing", "CRITICAL"),
                _finding("pricing", "CRITICAL"),
                _finding("trust", "WARNING"),
            ],
            [_finding("pricing", "CRITICAL"), _finding("onboarding", "INFO")],
        )
    )
    by_arch = {row["architect_name"]: row for row in out["by_architect"]}
    assert by_arch["pricing"]["finding_count"] == 3
    assert by_arch["pricing"]["critical_count"] == 3
    assert by_arch["trust"]["finding_count"] == 1
    assert by_arch["trust"]["warning_count"] == 1
    assert by_arch["onboarding"]["finding_count"] == 1
    assert by_arch["onboarding"]["info_count"] == 1


def test_aggregate_sorts_by_count_then_critical_then_name() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    # Equal counts -> tiebreaker is critical_count DESC.
    out = aggregate_findings(
        _sims(
            [
                _finding("a", "CRITICAL"),
                _finding("b", "CRITICAL"),
                _finding("a", "WARNING"),
            ],
            [
                _finding("a", "CRITICAL"),
                _finding("b", "WARNING"),
            ],
        )
    )
    names = [row["architect_name"] for row in out["by_architect"]]
    # a has 3 findings, b has 2 -> a first.
    assert names[0] == "a"
    assert names[1] == "b"


def test_aggregate_top_n_caps_top_architects() -> None:
    from app.simulation.findings_aggregate import (
        DEFAULT_TOP_N,
        aggregate_findings,
    )

    sims = _sims(
        [
            _finding("a", "CRITICAL"),
            _finding("b", "CRITICAL"),
            _finding("c", "CRITICAL"),
            _finding("d", "CRITICAL"),
            _finding("e", "CRITICAL"),
            _finding("f", "CRITICAL"),
        ],
    )
    out = aggregate_findings(sims, top_n=2)
    assert len(out["top_architects"]) == 2
    # Default top_n yields 5.
    default_out = aggregate_findings(sims)
    assert len(default_out["top_architects"]) == min(DEFAULT_TOP_N, 6)


def test_aggregate_shared_domain_count_requires_majority() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    # 4 sims; pricing tops 3 of them -> shared.
    out = aggregate_findings(
        _sims(
            [_finding("pricing", "CRITICAL")],
            [_finding("pricing", "CRITICAL")],
            [_finding("pricing", "CRITICAL")],
            [_finding("trust", "CRITICAL")],
        )
    )
    assert out["shared_domain_count"] == 1

    # 4 sims; pricing tops 1 -> not shared.
    out = aggregate_findings(
        _sims(
            [_finding("pricing", "CRITICAL")],
            [_finding("trust", "CRITICAL")],
            [_finding("onboarding", "CRITICAL")],
            [_finding("retention", "CRITICAL")],
        )
    )
    assert out["shared_domain_count"] == 0


def test_aggregate_handles_missing_results_json() -> None:
    """Defensive — None / non-dict payloads shouldn't crash."""
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings([None, {}, {"domain_findings": None}, "not a dict"])
    assert out["total_findings"] == 0
    assert out["filtered_findings"] == 0


def test_aggregate_handles_legacy_findings_key() -> None:
    """Older persisted shape uses ``findings`` instead of
    ``domain_findings`` — both must be accepted."""
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings(
        [
            {"findings": [_finding("pricing", "CRITICAL")]},
            {"domain_findings": [_finding("pricing", "CRITICAL")]},
        ]
    )
    assert out["total_findings"] == 2


def test_aggregate_handles_legacy_results_is_list() -> None:
    """Oldest shape: results_json is a list of findings directly."""
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings([[_finding("pricing", "CRITICAL")]])
    assert out["total_findings"] == 1


def test_aggregate_total_conversion_impact_sums() -> None:
    from app.simulation.findings_aggregate import aggregate_findings

    out = aggregate_findings(
        _sims(
            [
                _finding("pricing", "CRITICAL", impact=0.10),
                _finding("pricing", "WARNING", impact=0.05),
            ],
            [_finding("pricing", "CRITICAL", impact=0.20)],
        )
    )
    pricing = next(r for r in out["by_architect"] if r["architect_name"] == "pricing")
    assert pricing["total_conversion_impact"] == pytest.approx(0.35)


def test_aggregate_valid_severities_shape() -> None:
    """Pin the public allowlist."""
    from app.simulation.findings_aggregate import VALID_SEVERITIES

    assert set(VALID_SEVERITIES) == {"CRITICAL", "WARNING", "INFO"}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_findings_aggregate_out_default_shape() -> None:
    from app.schemas.simulation import FindingsAggregateOut

    out = FindingsAggregateOut()
    assert out.total_findings == 0
    assert out.filtered_findings == 0
    assert out.severity_breakdown == {}
    assert out.by_architect == []
    assert out.top_architects == []
    assert out.simulation_count == 0
    assert out.simulations_with_findings == 0
    assert out.shared_domain_count == 0


def test_findings_aggregate_out_with_data() -> None:
    from app.schemas.simulation import FindingsAggregateOut

    out = FindingsAggregateOut(
        total_findings=10,
        filtered_findings=4,
        severity_breakdown={"CRITICAL": 4, "WARNING": 6},
        by_architect=[{"architect_name": "pricing", "finding_count": 4}],
        top_architects=["pricing"],
        simulation_count=5,
        simulations_with_findings=3,
        shared_domain_count=1,
    )
    assert out.shared_domain_count == 1
    assert out.top_architects == ["pricing"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_aggregate_route_registered() -> None:
    """GET /simulations/aggregate/findings must appear in the router."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/aggregate/findings" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/simulations/aggregate/findings"]


def test_aggregate_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is documented."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if (
            r.path == "/simulations/aggregate/findings"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "min_severity" in query_param_names
            assert "top_n" in query_param_names
            return
    raise AssertionError("GET /simulations/aggregate/findings route not found")