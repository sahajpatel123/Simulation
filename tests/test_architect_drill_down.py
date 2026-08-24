"""
Tests for the per-architect drill-down helper + schema + route
registration.

The drill-down logic is pure-Python so we can exercise it
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
    from app.simulation import architect_drill_down

    assert set(architect_drill_down.__all__) == {
        "DEFAULT_OUTLIER_FINDING_THRESHOLD",
        "UNDER_OBSERVED_RATIO",
        "LOW_VARIANCE_MAX_CV",
        "MODERATE_VARIANCE_MAX_CV",
        "LOW_CALIBRATION_THRESHOLD",
        "PEER_PEAK_BAND",
        "PEER_ABOVE",
        "PEER_BELOW",
        "PEER_AT_PEAK",
        "PEER_UNKNOWN",
        "LABEL_HIGH_VARIANCE",
        "LABEL_MODERATE_VARIANCE",
        "LABEL_LOW_VARIANCE",
        "MAX_CRITICAL_CLUSTERS",
        "RECO_COLLECT_MORE_OUTCOMES",
        "RECO_INVESTIGATE_BIAS",
        "RECO_INVESTIGATE_OUTLIERS",
        "RECO_RECALIBRATE_VARIANCE",
        "RECO_TRUSTED",
        "build_architect_drill_down",
    }


# ---------------------------------------------------------------------------
# build_architect_drill_down — empty input
# ---------------------------------------------------------------------------


def test_drill_down_empty_returns_profile_only() -> None:
    """No sims → per_sim_history empty, aggregate zeros."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        product_types=["saas", "marketplace"],
        domain_description="Evaluates price ceilings and freemium.",
    )
    p = out["architect_profile"]
    assert p["architect_name"] == "PricingArchitect"
    assert p["product_types"] == ["saas", "marketplace"]
    assert p["domain_description"] == (
        "Evaluates price ceilings and freemium."
    )
    assert p["applies_to_all_products"] is False
    assert out["per_sim_history"] == []
    assert out["aggregate"]["finding_count"] == 0
    assert out["sim_count"] == 0


def test_drill_down_applies_to_all_when_product_types_empty() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "MacroeconomicArchitect",
        product_types=[],
    )
    assert out["architect_profile"]["applies_to_all_products"] is True


# ---------------------------------------------------------------------------
# Per-sim history
# ---------------------------------------------------------------------------


def _finding(severity: str, impact: float = 0.05) -> dict:
    return {
        "architect_name": "PricingArchitect",
        "severity": severity,
        "conversion_impact": impact,
    }


def test_drill_down_per_sim_history_filters_to_target_architect() -> None:
    """Only findings from the named architect feed the per-sim
    row — other architects in the same sim are ignored."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [
                    _finding("CRITICAL", 0.10),
                    {
                        "architect_name": "TrustArchitect",
                        "severity": "WARNING",
                        "conversion_impact": 0.05,
                    },
                ],
            ),
        ],
    )
    row = out["per_sim_history"][0]
    assert row["sim_id"] == 101
    assert row["finding_count"] == 1
    assert row["critical_count"] == 1


def test_drill_down_per_sim_history_keeps_sim_with_no_findings() -> None:
    """A sim with no findings from this architect still gets a
    row so the dashboard can render 'X of Y saw this
    architect'."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, []),
            (
                102,
                [_finding("CRITICAL")],
            ),
        ],
    )
    history = out["per_sim_history"]
    assert len(history) == 2
    by_id = {r["sim_id"]: r for r in history}
    assert by_id[101]["finding_count"] == 0
    assert by_id[102]["finding_count"] == 1


def test_drill_down_per_sim_history_sorted_by_sim_id() -> None:
    """Sorted by sim_id ASC; None sim_ids go last."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (203, [_finding("CRITICAL")]),
            (101, [_finding("WARNING")]),
            (None, [_finding("CRITICAL")]),
        ],
    )
    sim_ids = [r["sim_id"] for r in out["per_sim_history"]]
    assert sim_ids == [101, 203, None]


def test_drill_down_per_sim_history_carries_highest_severity() -> None:
    """``highest_severity`` is the most severe severity on the
    sim for this architect."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [
                    _finding("INFO"),
                    _finding("WARNING"),
                    _finding("CRITICAL"),
                    _finding("INFO"),
                ],
            ),
        ],
    )
    assert out["per_sim_history"][0]["highest_severity"] == "CRITICAL"


def test_drill_down_is_outlier_when_finding_count_above_threshold() -> None:
    """Per-sim finding count > threshold → is_outlier=True."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [_finding("WARNING") for _ in range(7)],
            ),
        ],
        outlier_finding_threshold=5,
    )
    assert out["per_sim_history"][0]["is_outlier"] is True
    assert out["aggregate"]["is_outlier_count"] == 1


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


def test_drill_down_aggregate_severity_counts() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [_finding("CRITICAL"), _finding("WARNING")],
            ),
            (102, [_finding("INFO")]),
        ],
    )
    a = out["aggregate"]
    assert a["finding_count"] == 3
    assert a["critical_count"] == 1
    assert a["warning_count"] == 1
    assert a["info_count"] == 1
    assert a["sim_with_findings_count"] == 2


def test_drill_down_aggregate_total_conversion_impact() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [_finding("CRITICAL", 0.10), _finding("WARNING", 0.05)],
            ),
        ],
    )
    assert out["aggregate"]["total_conversion_impact"] == pytest.approx(
        0.15
    )


# ---------------------------------------------------------------------------
# Stability / coverage / needs_attention
# ---------------------------------------------------------------------------


def test_drill_down_observation_ratio_fraction() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL")]),
            (102, []),
            (103, []),
        ],
    )
    assert out["aggregate"]["sim_with_findings_count"] == 1
    assert out["sim_count"] == 3
    assert out["observation_ratio"] == pytest.approx(1 / 3)


def test_drill_down_under_observed_below_30_percent() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[(101, [_finding("CRITICAL")])]
        + [(i, []) for i in range(102, 112)],
    )
    assert out["observation_ratio"] < 0.30
    assert out["under_observed"] is True


def test_drill_down_stability_low_variance_for_consistent_impacts() -> None:
    from app.simulation.architect_drill_down import (
        LABEL_LOW_VARIANCE,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("WARNING", 0.10)]),
            (102, [_finding("WARNING", 0.10)]),
        ],
    )
    assert out["stability"] == LABEL_LOW_VARIANCE


def test_drill_down_stability_high_variance_for_spread_impacts() -> None:
    from app.simulation.architect_drill_down import (
        LABEL_HIGH_VARIANCE,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("WARNING", 0.05)]),
            (102, [_finding("WARNING", 0.30)]),
        ],
    )
    assert out["stability"] == LABEL_HIGH_VARIANCE


def test_drill_down_needs_attention_includes_bias_signal() -> None:
    """A |calibration_variance| above the LOW_CALIBRATION_THRESHOLD
    flips needs_attention=True even with low variance + well
    observed data."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL", 0.10)]),
            (102, [_finding("CRITICAL", 0.10)]),
        ],
        calibration_variance=0.10,  # well above 0.02 threshold
    )
    assert out["under_observed"] is False
    assert out["stability"] != "HIGH_VARIANCE"
    assert out["needs_attention"] is True


# ---------------------------------------------------------------------------
# recommendation
# ---------------------------------------------------------------------------


def test_drill_down_recommendation_collect_for_under_observed() -> None:
    from app.simulation.architect_drill_down import (
        RECO_COLLECT_MORE_OUTCOMES,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[(101, [_finding("CRITICAL")])]
        + [(i, []) for i in range(102, 112)],
    )
    assert out["recommendation"] == RECO_COLLECT_MORE_OUTCOMES


def test_drill_down_recommendation_investigate_bias_for_high_variance() -> None:
    from app.simulation.architect_drill_down import (
        RECO_INVESTIGATE_BIAS,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL")]),
            (102, [_finding("CRITICAL")]),
        ],
        calibration_variance=0.05,
    )
    assert out["under_observed"] is False
    assert out["recommendation"] == RECO_INVESTIGATE_BIAS


def test_drill_down_recommendation_recalibrate_for_high_impact_variance() -> None:
    from app.simulation.architect_drill_down import (
        RECO_RECALIBRATE_VARIANCE,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL", 0.05)]),
            (102, [_finding("CRITICAL", 0.30)]),
        ],
    )
    assert out["under_observed"] is False
    # |calibration_variance| = 0 (None default), bias not flagged.
    assert out["stability"] == "HIGH_VARIANCE"
    assert out["recommendation"] == RECO_RECALIBRATE_VARIANCE


def test_drill_down_recommendation_trusted_for_well_calibrated() -> None:
    """Low variance, well-observed, no bias, no outliers →
    TRUSTED."""
    from app.simulation.architect_drill_down import (
        RECO_TRUSTED,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("WARNING", 0.05)]),
            (102, [_finding("WARNING", 0.05)]),
            (103, [_finding("WARNING", 0.05)]),
        ],
        calibration_variance=0.005,
    )
    assert out["under_observed"] is False
    assert out["stability"] != "HIGH_VARIANCE"
    assert out["aggregate"]["is_outlier_count"] == 0
    assert abs(out["calibration_variance"]) < 0.02
    assert out["recommendation"] == RECO_TRUSTED


# ---------------------------------------------------------------------------
# peer_comparison
# ---------------------------------------------------------------------------


def test_drill_down_peer_comparison_above_when_above_batch() -> None:
    from app.simulation.architect_drill_down import (
        PEER_ABOVE,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        calibration_variance=0.10,
        batch_overall_abs_variance=0.02,
    )
    pc = out["peer_comparison"]
    assert pc["architect_abs_variance"] == pytest.approx(0.10)
    assert pc["batch_overall_abs_variance"] == pytest.approx(0.02)
    assert pc["delta"] == pytest.approx(0.08)
    assert pc["direction"] == PEER_ABOVE


def test_drill_down_peer_comparison_at_peak_within_band() -> None:
    from app.simulation.architect_drill_down import (
        PEER_AT_PEAK,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        calibration_variance=0.020,
        batch_overall_abs_variance=0.025,
    )
    # Delta = -0.005, within 0.01 band → AT_PEAK.
    assert out["peer_comparison"]["direction"] == PEER_AT_PEAK


def test_drill_down_peer_comparison_unknown_when_batch_absent() -> None:
    from app.simulation.architect_drill_down import (
        PEER_UNKNOWN,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        calibration_variance=0.05,
    )
    pc = out["peer_comparison"]
    assert pc["batch_overall_abs_variance"] is None
    assert pc["delta"] is None
    assert pc["direction"] == PEER_UNKNOWN


def test_drill_down_peer_comparison_unknown_when_arch_absent() -> None:
    from app.simulation.architect_drill_down import (
        PEER_UNKNOWN,
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        batch_overall_abs_variance=0.05,
    )
    assert out["peer_comparison"]["architect_abs_variance"] is None
    assert out["peer_comparison"]["direction"] == PEER_UNKNOWN


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_architect_drill_down_out_default_shape() -> None:
    from app.schemas.simulation import ArchitectDrillDownOut

    out = ArchitectDrillDownOut()
    assert out.architect_profile == {}
    assert out.per_sim_history == []
    assert out.aggregate == {}
    assert out.calibration_variance is None
    assert out.calibration_direction == "INSUFFICIENT_DATA"
    assert out.stability == "INSUFFICIENT_DATA"
    assert out.observation_ratio == 0.0
    assert out.under_observed is False
    assert out.needs_attention is False
    assert out.sim_count == 0
    assert out.recommendation == "Continue — architect is calibrated"
    assert out.peer_comparison == {}
    assert out.critical_clusters == []
    assert out.severity_timeline == []


def test_architect_drill_down_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_architect_drill_down(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ArchitectDrillDownOut
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    payload = build_architect_drill_down(
        "PricingArchitect",
        product_types=["saas"],
        per_sim_findings=[(101, [_finding("CRITICAL")])],
        calibration_variance=0.05,
    )
    out = ArchitectDrillDownOut(**payload)
    assert out.architect_profile["architect_name"] == "PricingArchitect"
    assert out.aggregate["finding_count"] == 1
    assert out.calibration_variance == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# critical_clusters
# ---------------------------------------------------------------------------


def test_drill_down_critical_clusters_empty_when_no_critical() -> None:
    """No CRITICAL findings → empty list."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("INFO"), _finding("WARNING")]),
        ],
    )
    assert out["critical_clusters"] == []


def test_drill_down_critical_clusters_only_target_architect() -> None:
    """CRITICAL findings from other architects in the same sim
    must NOT count."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [
                    {
                        "architect_name": "PricingArchitect",
                        "cluster_id": "metro_pro",
                        "severity": "CRITICAL",
                    },
                    {
                        "architect_name": "TrustArchitect",
                        "cluster_id": "students",
                        "severity": "CRITICAL",
                    },
                ],
            ),
        ],
    )
    # Only Pricing's CRITICAL counts.
    assert len(out["critical_clusters"]) == 1
    assert out["critical_clusters"][0]["cluster_id"] == "metro_pro"


def test_drill_down_critical_clusters_aggregates_across_sims() -> None:
    """Two CRITICALs from cluster 'metro_pro' across two sims
    → critical_count=2."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    def crit(cluster_id: str, cluster_name: str = "Metro Pro") -> dict:
        return {
            "architect_name": "PricingArchitect",
            "cluster_id": cluster_id,
            "cluster_name": cluster_name,
            "severity": "CRITICAL",
        }

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [crit("metro_pro"), crit("students")]),
            (102, [crit("metro_pro")]),
        ],
    )
    rows = {r["cluster_id"]: r for r in out["critical_clusters"]}
    assert rows["metro_pro"]["critical_count"] == 2
    assert rows["students"]["critical_count"] == 1


def test_drill_down_critical_clusters_sorted_by_count_then_id() -> None:
    """Tiebreaker: cluster_id ASC."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    def crit(cluster_id: str) -> dict:
        return {
            "architect_name": "PricingArchitect",
            "cluster_id": cluster_id,
            "severity": "CRITICAL",
        }

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [crit("zebra"), crit("alpha")]),
        ],
    )
    # Both have count=1 → alpha first by tiebreaker.
    ids = [r["cluster_id"] for r in out["critical_clusters"]]
    assert ids == ["alpha", "zebra"]


def test_drill_down_critical_clusters_capped_at_max() -> None:
    """Cap keeps the dashboard tile readable."""
    from app.simulation.architect_drill_down import (
        MAX_CRITICAL_CLUSTERS,
        build_architect_drill_down,
    )

    findings = [
        {
            "architect_name": "PricingArchitect",
            "cluster_id": f"c{i}",
            "severity": "CRITICAL",
        }
        for i in range(10)
    ]
    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[(101, findings)],
    )
    assert len(out["critical_clusters"]) == MAX_CRITICAL_CLUSTERS
    assert MAX_CRITICAL_CLUSTERS == 5


def test_drill_down_critical_clusters_skips_missing_cluster_id() -> None:
    """A CRITICAL finding without a cluster_id must not crash
    the aggregation — it's skipped."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (
                101,
                [
                    {
                        "architect_name": "PricingArchitect",
                        # No cluster_id.
                        "severity": "CRITICAL",
                    },
                    {
                        "architect_name": "PricingArchitect",
                        "cluster_id": "metro_pro",
                        "severity": "CRITICAL",
                    },
                ],
            ),
        ],
    )
    assert len(out["critical_clusters"]) == 1
    assert out["critical_clusters"][0]["cluster_id"] == "metro_pro"


# ---------------------------------------------------------------------------
# severity_timeline
# ---------------------------------------------------------------------------


def test_drill_down_severity_timeline_empty_for_no_sims() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down("PricingArchitect")
    assert out["severity_timeline"] == []


def test_drill_down_severity_timeline_carries_per_sim_counts() -> None:
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL"), _finding("WARNING")]),
            (102, [_finding("INFO")]),
        ],
    )
    timeline = out["severity_timeline"]
    assert len(timeline) == 2
    # Sim 101: 1 critical, 1 warning, 0 info.
    by_id = {r["sim_id"]: r for r in timeline}
    assert by_id[101]["critical_count"] == 1
    assert by_id[101]["warning_count"] == 1
    assert by_id[101]["info_count"] == 0
    assert by_id[101]["finding_count"] == 2


def test_drill_down_severity_timeline_cumulative_totals() -> None:
    """Cumulative totals grow monotonically across the timeline."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (101, [_finding("CRITICAL")]),
            (102, [_finding("CRITICAL"), _finding("WARNING")]),
            (103, []),
        ],
    )
    timeline = out["severity_timeline"]
    # Cumulative after sim 101: 1 CRITICAL.
    assert timeline[0]["cumulative_critical"] == 1
    assert timeline[0]["cumulative_total"] == 1
    # Cumulative after sim 102: 2 CRITICAL, 1 WARNING.
    assert timeline[1]["cumulative_critical"] == 2
    assert timeline[1]["cumulative_warning"] == 1
    assert timeline[1]["cumulative_total"] == 3
    # Cumulative after sim 103 (no findings): unchanged.
    assert timeline[2]["cumulative_critical"] == 2
    assert timeline[2]["cumulative_total"] == 3


def test_drill_down_severity_timeline_sorted_by_sim_id() -> None:
    """Sorted by sim_id ASC; None sim_ids go last."""
    from app.simulation.architect_drill_down import (
        build_architect_drill_down,
    )

    out = build_architect_drill_down(
        "PricingArchitect",
        per_sim_findings=[
            (203, [_finding("CRITICAL")]),
            (101, [_finding("CRITICAL")]),
            (None, [_finding("CRITICAL")]),
        ],
    )
    sim_ids = [r["sim_id"] for r in out["severity_timeline"]]
    assert sim_ids == [101, 203, None]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_architect_drill_down_route_registered() -> None:
    """GET /simulations/architect-drill-down must appear in the
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
    assert "/simulations/architect-drill-down" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/architect-drill-down"]
    )


def test_architect_drill_down_route_query_params() -> None:
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
            r.path == "/simulations/architect-drill-down"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "architect_name" in query_param_names
            assert "ids" in query_param_names
            assert "outlier_finding_threshold" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/architect-drill-down route not found"
    )
