"""
Tests for the cross-simulation portfolio summary helper + schema
+ route registration.

The composition logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
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
    from app.simulation import portfolio_summary

    assert set(portfolio_summary.__all__) == {
        "LABEL_HEALTHY",
        "LABEL_NEEDS_ATTENTION",
        "LABEL_CRITICAL",
        "LABEL_INSUFFICIENT_DATA",
        "VALID_HEALTH_LABELS",
        "build_portfolio_summary",
    }


def test_health_label_allowlist_pinned() -> None:
    """Lock the health enum so a rename breaks here rather than
    silently at the dashboard."""
    from app.simulation.portfolio_summary import VALID_HEALTH_LABELS

    assert set(VALID_HEALTH_LABELS) == {
        "HEALTHY",
        "NEEDS_ATTENTION",
        "CRITICAL",
        "INSUFFICIENT_DATA",
    }


# ---------------------------------------------------------------------------
# build_portfolio_summary — empty input
# ---------------------------------------------------------------------------


def test_summary_with_no_sims_returns_zero_defaults() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(simulation_count=0)
    assert out["simulation_count"] == 0
    assert out["correlated_bias_count"] == 0
    assert out["data_quality_score"] == 0.0
    assert out["overall_health"] == "INSUFFICIENT_DATA"


def test_summary_handles_missing_sub_payloads() -> None:
    """All four sub-payloads default to ``{}`` so the route can
    safely pass them as ``None`` while it's still warming up."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        findings_payload=None,
        outcomes_payload=None,
        clusters_payload=None,
        architect_accuracy_payload=None,
    )
    assert out["findings_summary"] == {
        "total_findings": 0,
        "filtered_findings": 0,
        "severity_breakdown": {},
        "shared_domain_count": 0,
        "top_critical_architects": [],
        "simulations_with_findings": 0,
    }
    assert out["outcomes_summary"]["confidence_label"] == (
        "INSUFFICIENT_DATA"
    )


# ---------------------------------------------------------------------------
# build_portfolio_summary — findings summary
# ---------------------------------------------------------------------------


def test_summary_findings_reduced_correctly() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    findings = {
        "total_findings": 30,
        "filtered_findings": 12,
        "severity_breakdown": {"CRITICAL": 5, "WARNING": 7, "INFO": 18},
        "by_architect": [],
        "by_cluster": [],
        "top_architects": ["pricing", "trust"],
        "top_findings": [],
        "simulation_count": 12,
        "simulations_with_findings": 9,
        "shared_domain_count": 2,
        "architect_filter": None,
    }
    out = build_portfolio_summary(
        simulation_count=12, findings_payload=findings,
    )
    summary = out["findings_summary"]
    assert summary["total_findings"] == 30
    assert summary["filtered_findings"] == 12
    assert summary["severity_breakdown"] == {
        "CRITICAL": 5, "WARNING": 7, "INFO": 18,
    }
    assert summary["shared_domain_count"] == 2
    assert summary["top_critical_architects"] == ["pricing", "trust"]
    assert summary["simulations_with_findings"] == 9


def test_summary_findings_top_critical_capped_at_five() -> None:
    """``top_critical_architects`` is capped at 5 so the
    intersection with ``most_biased_architects`` stays meaningful."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    findings = {
        "total_findings": 10,
        "filtered_findings": 5,
        "severity_breakdown": {},
        "top_architects": [
            "a1", "a2", "a3", "a4", "a5", "a6", "a7",
        ],
        "simulation_count": 5,
        "simulations_with_findings": 5,
        "shared_domain_count": 0,
    }
    out = build_portfolio_summary(
        simulation_count=5, findings_payload=findings,
    )
    assert out["findings_summary"]["top_critical_architects"] == [
        "a1", "a2", "a3", "a4", "a5",
    ]


# ---------------------------------------------------------------------------
# build_portfolio_summary — outcomes summary
# ---------------------------------------------------------------------------


def test_summary_outcomes_reduced_correctly() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    outcomes = {
        "mae": 0.05,
        "mape": 0.20,
        "rmse": 0.07,
        "mae_count": 8,
        "mape_count": 7,
        "outlier_count": 2,
        "direction_breakdown": {"over": 5, "under": 2, "exact": 1},
        "per_pair": [],
        "simulation_count": 10,
        "with_predictions": 8,
        "worst_offender_sim_id": 42,
        "confidence_label": "NEEDS_ATTENTION",
    }
    out = build_portfolio_summary(
        simulation_count=10, outcomes_payload=outcomes,
    )
    s = out["outcomes_summary"]
    assert s["mae"] == pytest.approx(0.05)
    assert s["mape"] == pytest.approx(0.20)
    assert s["rmse"] == pytest.approx(0.07)
    assert s["mae_count"] == 8
    assert s["outlier_count"] == 2
    assert s["direction_breakdown"] == {
        "over": 5, "under": 2, "exact": 1,
    }
    assert s["confidence_label"] == "NEEDS_ATTENTION"
    assert s["worst_offender_sim_id"] == 42


# ---------------------------------------------------------------------------
# build_portfolio_summary — clusters summary
# ---------------------------------------------------------------------------


def test_summary_clusters_reduced_correctly() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    clusters = {
        "by_cluster": [],
        "top_laggards": ["metro_pro", "tier3"],
        "top_performers": ["students"],
        "simulation_count": 5,
        "clusters_seen": 12,
        "under_observed_count": 1,
        "needs_attention_count": 3,
    }
    out = build_portfolio_summary(
        simulation_count=5, clusters_payload=clusters,
    )
    assert out["clusters_summary"]["clusters_seen"] == 12
    assert out["clusters_summary"]["needs_attention_count"] == 3
    assert out["clusters_summary"]["top_laggards"] == [
        "metro_pro", "tier3",
    ]


# ---------------------------------------------------------------------------
# build_portfolio_summary — architect accuracy summary
# ---------------------------------------------------------------------------


def test_summary_architect_accuracy_reduced_correctly() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    bridge = {
        "by_architect": [],
        "most_biased_architects": ["pricing", "trust"],
        "simulation_count": 5,
        "outcome_attached_sim_count": 3,
        "tighten_count": 1,
        "loosen_count": 1,
        "trusted_count": 1,
        "insufficient_data_count": 1,
        "min_severity": "INFO",
    }
    out = build_portfolio_summary(
        simulation_count=5,
        architect_accuracy_payload=bridge,
    )
    s = out["architect_accuracy_summary"]
    assert s["outcome_attached_sim_count"] == 3
    assert s["tighten_count"] == 1
    assert s["loosen_count"] == 1
    assert s["trusted_count"] == 1
    assert s["insufficient_data_count"] == 1
    assert s["most_biased_architects"] == ["pricing", "trust"]


# ---------------------------------------------------------------------------
# build_portfolio_summary — correlated_bias_count
# ---------------------------------------------------------------------------


def test_summary_correlated_bias_count_case_insensitive() -> None:
    """``Pricing`` in findings and ``pricing`` in bridge must
    match — the intersection is case-folded."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    findings = {
        "top_architects": ["Pricing", "TRUST"],
        "simulations_with_findings": 4,
    }
    bridge = {
        "most_biased_architects": ["pricing", "TRUST", "retention"],
        "outcome_attached_sim_count": 4,
    }
    out = build_portfolio_summary(
        simulation_count=4,
        findings_payload=findings,
        architect_accuracy_payload=bridge,
    )
    # "Pricing" matches "pricing" (1); "TRUST" matches "TRUST" (1)
    # → total 2.
    assert out["correlated_bias_count"] == 2


def test_summary_correlated_bias_count_no_overlap_is_zero() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    findings = {"top_architects": ["pricing", "trust"]}
    bridge = {"most_biased_architects": ["retention", "onboarding"]}
    out = build_portfolio_summary(
        simulation_count=4,
        findings_payload=findings,
        architect_accuracy_payload=bridge,
    )
    assert out["correlated_bias_count"] == 0


def test_summary_correlated_bias_count_ignores_empty_strings() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    findings = {"top_architects": ["", "pricing"]}
    bridge = {"most_biased_architects": ["", "PRICING"]}
    out = build_portfolio_summary(
        simulation_count=4,
        findings_payload=findings,
        architect_accuracy_payload=bridge,
    )
    # Empty strings don't match anything (and ``""`` matches ``""``
    # but they're filtered out by the truthy guard). Pricing
    # matches PRICING → 1.
    assert out["correlated_bias_count"] == 1


# ---------------------------------------------------------------------------
# build_portfolio_summary — data_quality_score
# ---------------------------------------------------------------------------


def test_summary_data_quality_score_uses_min() -> None:
    """Coverage = min(outcome_attached, sims_with_findings) /
    simulation_count."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=10,
        findings_payload={"simulations_with_findings": 8},
        architect_accuracy_payload={"outcome_attached_sim_count": 6},
    )
    assert out["data_quality_score"] == pytest.approx(0.6)


def test_summary_data_quality_score_clamps_to_one() -> None:
    """Defensive guard — if a count > simulation_count slips in
    (route bug), clamp to 1.0 rather than reporting >100% coverage."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        findings_payload={"simulations_with_findings": 8},
        architect_accuracy_payload={"outcome_attached_sim_count": 6},
    )
    assert out["data_quality_score"] == pytest.approx(1.0)


def test_summary_data_quality_score_zero_for_no_sims() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(simulation_count=0)
    assert out["data_quality_score"] == 0.0


# ---------------------------------------------------------------------------
# build_portfolio_summary — overall_health
# ---------------------------------------------------------------------------


def test_summary_overall_health_insufficient_when_no_outcomes() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        outcomes_payload={"confidence_label": "INSUFFICIENT_DATA"},
        architect_accuracy_payload={"outcome_attached_sim_count": 0},
    )
    assert out["overall_health"] == "INSUFFICIENT_DATA"


def test_summary_overall_health_insufficient_when_outcome_count_zero() -> None:
    """Defensive — outcome_count == 0 wins over confidence_label,
    even when confidence claims WELL_CALIBRATED (the label is
    meaningless with zero samples)."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        outcomes_payload={"confidence_label": "WELL_CALIBRATED"},
        architect_accuracy_payload={"outcome_attached_sim_count": 0},
    )
    assert out["overall_health"] == "INSUFFICIENT_DATA"


def test_summary_overall_health_critical_poorly_calibrated_and_correlated() -> None:
    """POORLY_CALIBRATED + ≥ 2 correlated bias architects → CRITICAL."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=10,
        findings_payload={
            "top_architects": ["pricing", "trust"],
            "simulations_with_findings": 9,
        },
        outcomes_payload={"confidence_label": "POORLY_CALIBRATED"},
        clusters_payload={"needs_attention_count": 0},
        architect_accuracy_payload={
            "most_biased_architects": ["pricing", "trust"],
            "outcome_attached_sim_count": 9,
        },
    )
    assert out["overall_health"] == "CRITICAL"


def test_summary_overall_health_critical_not_just_one_signal() -> None:
    """POORLY_CALIBRATED alone (only 1 correlated bias) → only
    NEEDS_ATTENTION, not CRITICAL. CRITICAL needs both signals."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=10,
        findings_payload={
            "top_architects": ["pricing"],
            "simulations_with_findings": 9,
        },
        outcomes_payload={"confidence_label": "POORLY_CALIBRATED"},
        clusters_payload={"needs_attention_count": 0},
        architect_accuracy_payload={
            "most_biased_architects": ["pricing"],
            "outcome_attached_sim_count": 9,
        },
    )
    assert out["overall_health"] == "NEEDS_ATTENTION"


def test_summary_overall_health_needs_attention_for_needs_attention_label() -> None:
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        outcomes_payload={"confidence_label": "NEEDS_ATTENTION"},
        architect_accuracy_payload={"outcome_attached_sim_count": 5},
    )
    assert out["overall_health"] == "NEEDS_ATTENTION"


def test_summary_overall_health_needs_attention_for_correlated_bias() -> None:
    """Even with WELL_CALIBRATED outcomes, a single correlated
    bias architect triggers NEEDS_ATTENTION."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        findings_payload={
            "top_architects": ["pricing"],
            "simulations_with_findings": 5,
        },
        outcomes_payload={"confidence_label": "WELL_CALIBRATED"},
        clusters_payload={"needs_attention_count": 0},
        architect_accuracy_payload={
            "most_biased_architects": ["pricing"],
            "outcome_attached_sim_count": 5,
        },
    )
    assert out["overall_health"] == "NEEDS_ATTENTION"


def test_summary_overall_health_needs_attention_for_cluster_attention() -> None:
    """≥ 2 clusters flagged needs_attention alone → NEEDS_ATTENTION."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        outcomes_payload={"confidence_label": "WELL_CALIBRATED"},
        clusters_payload={"needs_attention_count": 2},
        architect_accuracy_payload={
            "most_biased_architects": [],
            "outcome_attached_sim_count": 5,
        },
    )
    assert out["overall_health"] == "NEEDS_ATTENTION"


def test_summary_overall_health_healthy_for_clean_signals() -> None:
    """WELL_CALIBRATED + 0 correlated bias + < 2 needs_attention
    clusters → HEALTHY."""
    from app.simulation.portfolio_summary import build_portfolio_summary

    out = build_portfolio_summary(
        simulation_count=5,
        findings_payload={
            "top_architects": ["pricing"],
            "simulations_with_findings": 5,
        },
        outcomes_payload={"confidence_label": "WELL_CALIBRATED"},
        clusters_payload={"needs_attention_count": 1},
        architect_accuracy_payload={
            "most_biased_architects": ["retention"],  # no overlap
            "outcome_attached_sim_count": 5,
        },
    )
    assert out["overall_health"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_portfolio_summary_out_default_shape() -> None:
    from app.schemas.simulation import PortfolioSummaryOut

    out = PortfolioSummaryOut()
    assert out.simulation_count == 0
    assert out.findings_summary == {}
    assert out.outcomes_summary == {}
    assert out.clusters_summary == {}
    assert out.architect_accuracy_summary == {}
    assert out.correlated_bias_count == 0
    assert out.data_quality_score == 0.0
    assert out.overall_health == "INSUFFICIENT_DATA"


def test_portfolio_summary_out_round_trips_build_payload() -> None:
    """The route layer must wrap ``build_portfolio_summary(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import PortfolioSummaryOut
    from app.simulation.portfolio_summary import build_portfolio_summary

    payload = build_portfolio_summary(
        simulation_count=3,
        findings_payload={
            "total_findings": 5,
            "filtered_findings": 2,
            "severity_breakdown": {"CRITICAL": 2},
            "top_architects": ["pricing"],
            "simulations_with_findings": 2,
            "shared_domain_count": 1,
        },
        outcomes_payload={"confidence_label": "NEEDS_ATTENTION"},
        clusters_payload={"needs_attention_count": 0},
        architect_accuracy_payload={
            "outcome_attached_sim_count": 2,
            "tighten_count": 1,
            "most_biased_architects": ["pricing"],
        },
    )
    out = PortfolioSummaryOut(**payload)
    assert out.simulation_count == 3
    assert out.findings_summary["total_findings"] == 5
    assert out.correlated_bias_count == 1
    assert out.overall_health == "NEEDS_ATTENTION"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_portfolio_summary_route_registered() -> None:
    """GET /simulations/portfolio-summary must appear in the
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
    assert "/simulations/portfolio-summary" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/portfolio-summary"]


def test_portfolio_summary_route_query_params() -> None:
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
            r.path == "/simulations/portfolio-summary"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/portfolio-summary route not found"
    )