"""Unit tests for the simulation quality gate (``app.simulation.simulation_quality``).

Pure deterministic tests — no DB, no LLM, no network. Uses the real
52-cluster registry so coverage checks are realistic.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.simulation_quality import (
    COVERAGE_WARN,
    SEVERITY_CRITICAL,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_REVIEW,
    build_simulation_quality,
)


def _healthy_results(**overrides: object) -> dict:
    """Build a fully valid completed-results payload."""
    clusters = ClusterRegistry().all_clusters()
    rates = {
        c.cluster_id: round(0.03 + index * 0.0008, 6)
        for index, c in enumerate(clusters)
    }
    pwc = round(
        sum(c.population_weight * rates[c.cluster_id] for c in clusters),
        6,
    )
    converted = int(round(pwc * 10_000))
    results: dict = {
        "mean_conversion_rate": pwc,
        "population_weighted_conversion": pwc,
        "total_agents": 10_000,
        "converted": converted,
        "cluster_breakdown": rates,
        "domain_findings": [
            {"domain": "PricingArchitect", "severity": "WARNING"},
            {"domain": "TrustArchitect", "severity": "INFO"},
        ],
        "raw_funnel": {
            "total_agents": 10_000,
            "converted": converted,
            "conversion_rate": pwc,
            "stage_counts": {
                "ARRIVE": 10_000,
                "BROWSE": 7_000,
                "CONSIDER": 4_000,
                "DECIDE": 2_000,
                "PURCHASE": converted,
            },
            "stage_metrics": [
                {
                    "state": "ARRIVE",
                    "agent_count": 10_000,
                    "entry_rate": 1.0,
                    "drop_off_rate": 0.3,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "BROWSE",
                    "agent_count": 7_000,
                    "entry_rate": 0.7,
                    "drop_off_rate": 0.43,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "CONSIDER",
                    "agent_count": 4_000,
                    "entry_rate": 0.4,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "DECIDE",
                    "agent_count": 2_000,
                    "entry_rate": 0.2,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "PURCHASE",
                    "agent_count": converted,
                    "entry_rate": pwc,
                    "drop_off_rate": 0.0,
                    "avg_time_seconds": 1.0,
                },
            ],
        },
    }
    results.update(overrides)
    return results


def _run(results: dict | None = None) -> object:
    return build_simulation_quality(
        simulation_id=1,
        project_id=10,
        base_results=results if results is not None else _healthy_results(),
        status="COMPLETED",
        signal_quality=0.62,
    )


def _run_with_signal_quality(raw: object) -> object:
    return build_simulation_quality(
        simulation_id=1,
        project_id=10,
        base_results=_healthy_results(),
        status="COMPLETED",
        signal_quality=raw,  # type: ignore[arg-type]
    )


def _check(out: object, check_id: str) -> object:
    return next(c for c in out.checks if c.id == check_id)


# ── Healthy baseline ──────────────────────────────────────────────────


def test_healthy_results_score_perfect_pass() -> None:
    out = _run()
    assert out.trust_score == 1.0
    assert out.verdict == VERDICT_PASS
    assert out.signal_quality == 0.62
    assert out.summary.total_checks == 11
    assert out.summary.passed_checks == 11
    assert out.summary.failed_checks == 0
    assert out.summary.skipped_checks == 0
    assert out.recommendations == []
    assert out.meta["cluster_coverage_fraction"] == 1.0


def test_healthy_results_have_all_critical_checks() -> None:
    out = _run()
    critical = [c for c in out.checks if c.severity == SEVERITY_CRITICAL]
    assert len(critical) == 6
    assert all(c.passed is True for c in critical)


# ── Empty / corrupt payloads ──────────────────────────────────────────


def test_empty_results_fail_hard() -> None:
    out = _run({})
    assert out.trust_score < 0.60
    assert out.verdict == VERDICT_FAIL
    assert _check(out, "results_present").passed is False
    assert out.summary.passed_checks < out.summary.evaluated_checks


def test_string_json_results_are_coerced() -> None:
    out = _run(json.dumps(_healthy_results()))
    assert out.trust_score == 1.0
    assert out.verdict == VERDICT_PASS


def test_malformed_signal_quality_is_treated_as_missing() -> None:
    for bad in (float("nan"), float("inf"), -float("inf"), 1.5, -0.1):
        out = _run_with_signal_quality(bad)
        assert out.signal_quality is None


def test_numeric_string_signal_quality_is_coerced() -> None:
    out = _run_with_signal_quality("0.62")
    assert out.signal_quality == 0.62


def test_non_finite_values_flagged() -> None:
    results = _healthy_results()
    results["raw_funnel"]["stage_counts"]["BROWSE"] = float("inf")  # type: ignore[index]
    out = _run(results)
    assert _check(out, "nan_inf_free").passed is False
    assert out.trust_score < 1.0
    assert any("NaN/Inf" in rec for rec in out.recommendations)


def test_negative_nan_flagging() -> None:
    results = _healthy_results()
    results["mean_conversion_rate"] = float("nan")  # type: ignore[assignment]
    out = _run(results)
    assert _check(out, "nan_inf_free").passed is False


# ── Cluster coverage / rates ──────────────────────────────────────────


def test_partial_cluster_coverage_fails_coverage_check() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters}
    missing = [c.cluster_id for c in clusters[:5]]
    for cid in missing:
        breakdown.pop(cid, None)
    results = _healthy_results(cluster_breakdown=breakdown)
    out = _run(results)
    check = _check(out, "cluster_coverage")
    assert check.passed is False
    assert out.meta["cluster_coverage_fraction"] == round(47 / 52, 4)
    assert any("clusters are missing" in rec for rec in out.recommendations)


def test_out_of_range_cluster_rate_fails_rate_check() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters}
    breakdown[clusters[0].cluster_id] = 1.5
    results = _healthy_results(cluster_breakdown=breakdown)
    out = _run(results)
    assert _check(out, "cluster_rates_bounded").passed is False
    assert "out-of-range" in _check(out, "cluster_rates_bounded").detail


def test_unparseable_cluster_rate_fails_rate_check() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters}
    breakdown[clusters[0].cluster_id] = {"conversion_rate": "not-a-number"}
    results = _healthy_results(cluster_breakdown=breakdown)
    out = _run(results)
    assert _check(out, "cluster_rates_bounded").passed is False


def test_dict_cluster_entries_are_read() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {
        c.cluster_id: {"conversion_rate": 0.04} for c in clusters
    }
    results = _healthy_results(cluster_breakdown=breakdown)
    out = _run(results)
    assert _check(out, "cluster_rates_bounded").passed is True


# ── Counts / weighted blend ───────────────────────────────────────────


def test_converted_exceeding_total_fails_counts_check() -> None:
    results = _healthy_results()
    results["raw_funnel"]["converted"] = 20_000  # type: ignore[index]
    out = _run(results)
    assert _check(out, "agent_counts_consistent").passed is False
    assert any("exceeds total agents" in rec for rec in out.recommendations)


def test_headline_diverging_from_blend_fails_weighted_check() -> None:
    results = _healthy_results()
    results["population_weighted_conversion"] = 0.5
    out = _run(results)
    assert _check(out, "weighted_conversion_consistent").passed is False
    assert "diverges from weighted blend" in _check(
        out, "weighted_conversion_consistent"
    ).detail


def test_weighted_check_skipped_when_coverage_too_low() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters[:20]}
    results = _healthy_results(cluster_breakdown=breakdown)
    out = _run(results)
    check = _check(out, "weighted_conversion_consistent")
    assert check.skipped is True
    assert check.passed is None


def test_partial_coverage_consistent_blend_passes_weighted_check() -> None:
    # A partially persisted breakdown (>= 90% coverage) whose surviving
    # clusters are internally consistent must not be flagged as a
    # headline-vs-blend divergence. The blend is coverage-normalized, so
    # missing segments cannot manufacture a false "diverges" failure.
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters}
    for cid in [c.cluster_id for c in clusters[:5]]:
        breakdown.pop(cid, None)
    results = _healthy_results(
        cluster_breakdown=breakdown,
        population_weighted_conversion=0.04,
        mean_conversion_rate=0.04,
    )
    out = _run(results)
    check = _check(out, "weighted_conversion_consistent")
    assert check.passed is True
    assert "coverage-normalized" in check.detail
    # The gate must still surface the missing segments on its own check —
    # normalization only makes the blend comparison fair, it does not
    # mask partial coverage.
    assert _check(out, "cluster_coverage").passed is False
    assert not any(
        "diverges from weighted blend" in rec for rec in out.recommendations
    )


def test_partial_coverage_divergent_blend_fails_weighted_check() -> None:
    # Normalization must not hide a genuinely inconsistent headline:
    # with every surviving cluster at 0.04, a 0.10 headline is still a
    # real divergence and must fail the check.
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters}
    for cid in [c.cluster_id for c in clusters[:5]]:
        breakdown.pop(cid, None)
    results = _healthy_results(
        cluster_breakdown=breakdown,
        population_weighted_conversion=0.10,
        mean_conversion_rate=0.10,
    )
    out = _run(results)
    check = _check(out, "weighted_conversion_consistent")
    assert check.passed is False
    assert "diverges from weighted blend" in check.detail


def test_weighted_check_skipped_when_covered_weight_too_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defensive guard: even at full ID coverage, a breakdown whose covered
    # population weight is negligible cannot anchor a meaningful blend.
    results = _healthy_results()
    fake_clusters = [
        SimpleNamespace(cluster_id=f"fake_{i}", population_weight=0.005)
        for i in range(52)
    ]
    results["cluster_breakdown"] = {f"fake_{i}": 0.04 for i in range(52)}
    results["population_weighted_conversion"] = 0.04
    results["mean_conversion_rate"] = 0.04
    monkeypatch.setattr(
        ClusterRegistry,
        "_all_clusters_cache",
        fake_clusters,
    )
    out = _run(results)
    check = _check(out, "weighted_conversion_consistent")
    assert check.skipped is True
    assert check.passed is None
    assert "population weight" in check.detail


# ── Funnel sanity ─────────────────────────────────────────────────────


def test_funnel_counts_increasing_fails_monotonic_check() -> None:
    results = _healthy_results()
    results["raw_funnel"]["stage_counts"]["BROWSE"] = 12_000  # type: ignore[index]
    out = _run(results)
    assert _check(out, "funnel_counts_monotonic").passed is False
    assert "increase between" in _check(out, "funnel_counts_monotonic").detail


def test_funnel_metric_out_of_bounds_fails_metrics_check() -> None:
    results = _healthy_results()
    results["raw_funnel"]["stage_metrics"][1]["drop_off_rate"] = 1.7  # type: ignore[index]
    out = _run(results)
    assert _check(out, "funnel_metrics_bounded").passed is False


def test_legacy_results_without_raw_funnel_skip_funnel_checks() -> None:
    results = _healthy_results()
    results.pop("raw_funnel", None)
    out = _run(results)
    assert out.summary.skipped_checks == 2
    assert _check(out, "funnel_metrics_bounded").skipped is True
    assert _check(out, "funnel_counts_monotonic").skipped is True
    # Skipped checks do not penalise the score.
    assert out.trust_score == 1.0
    assert out.verdict == VERDICT_PASS


# ── Findings / verdict bands ──────────────────────────────────────────


def test_missing_domain_findings_is_minor_fail_only() -> None:
    results = _healthy_results(domain_findings=[])
    out = _run(results)
    check = _check(out, "domain_findings_present")
    assert check.passed is False
    assert out.summary.failed_checks == 1
    # A single minor failure keeps the run above the PASS threshold.
    assert out.verdict == VERDICT_PASS
    assert any("domain findings" in rec for rec in out.recommendations)


def test_mixed_failures_drop_verdict_to_review() -> None:
    clusters = ClusterRegistry().all_clusters()
    breakdown = {c.cluster_id: 0.04 for c in clusters[:30]}
    results = _healthy_results(
        cluster_breakdown=breakdown,
    )
    results["raw_funnel"]["converted"] = 20_000  # type: ignore[index]
    out = _run(results)
    assert _check(out, "agent_counts_consistent").passed is False
    assert _check(out, "cluster_coverage").passed is False
    assert 0.60 <= out.trust_score < 0.85
    assert out.verdict == VERDICT_REVIEW


def test_failed_quality_has_zero_trust_on_all_missing() -> None:
    out = _run(
        {
            "mean_conversion_rate": None,
            "cluster_breakdown": {},
        }
    )
    assert out.verdict == VERDICT_FAIL
    assert out.trust_score < 0.60
    assert out.summary.failed_checks > 0


def test_coverage_warn_threshold_constant_is_sane() -> None:
    assert 0.0 < COVERAGE_WARN < 1.0
