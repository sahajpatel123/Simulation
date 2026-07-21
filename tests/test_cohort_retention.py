"""
Tests for the cohort retention projection engine
(cycle 30 cohort-retention-projection).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.cohort_retention import (
    BENCHMARK_SURVIVAL,
    CHURN_TRIGGER_MAP,
    RETENTION_DAYS,
    _churn_risk_label,
    _churn_risk_score,
    _compute_survival_curve,
    build_cohort_retention,
)
from app.schemas.cohort_retention import (
    CohortRetentionOut,
    ClusterRetentionProfile,
    RetentionCurvePoint,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BREAKDOWN: dict[str, Any] = {
    "metro_power_professional": 0.08,
    "tier2_price_sensitive_pragmatist": 0.02,
    "anxiety_driven_researcher": 0.01,
    "high_literacy_student_freemium_ceiling": 0.03,
}

REGISTRY: dict[str, dict[str, Any]] = {
    "metro_power_professional": {"name": "Metro Power Professional", "population_weight": 0.20},
    "tier2_price_sensitive_pragmatist": {"name": "Tier-2 Price Sensitive", "population_weight": 0.15},
    "anxiety_driven_researcher": {"name": "Anxiety Driven Researcher", "population_weight": 0.10},
    "high_literacy_student_freemium_ceiling": {"name": "Student Freemium Ceiling", "population_weight": 0.12},
}


def _results(
    *,
    cr: float = 0.05,
    total: int = 10000,
    domain_findings: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> dict[str, Any]:
    converted = int(round(cr * total))
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": total,
        "converted": converted,
        "product_type_detected": product_type,
        "cluster_breakdown": dict(BREAKDOWN),
        "domain_findings": domain_findings or [],
    }


def _retention_finding(
    cid: str,
    metric: str,
    actual: float,
    benchmark: float = 0.5,
    severity: str = "WARNING",
) -> dict[str, Any]:
    return {
        "architect_name": "RetentionArchitect",
        "cluster_id": cid,
        "cluster_name": REGISTRY.get(cid, {}).get("name", cid),
        "population_fraction": REGISTRY.get(cid, {}).get("population_weight", 0.02),
        "finding": f"{metric} is below benchmark",
        "metric_affected": metric,
        "actual_value": actual,
        "healthy_benchmark": benchmark,
        "delta": actual - benchmark,
        "conversion_impact": -0.01,
        "recommended_action": "Improve retention",
        "affected_agent_count": 100,
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# Survival curve computation
# ---------------------------------------------------------------------------

class TestSurvivalCurve:
    def test_curve_has_all_days(self) -> None:
        curve = _compute_survival_curve(0.05, {}, benchmark_cr=0.05)
        assert len(curve) == len(RETENTION_DAYS)
        assert RETENTION_DAYS == [1, 7, 30, 90, 180, 365]

    def test_curve_monotonically_non_increasing(self) -> None:
        curve = _compute_survival_curve(0.05, {}, benchmark_cr=0.05)
        for i in range(1, len(curve)):
            assert curve[i] <= curve[i - 1] + 1e-9, (
                f"Survival at day {RETENTION_DAYS[i]} ({curve[i]}) "
                f"should not exceed day {RETENTION_DAYS[i-1]} ({curve[i-1]})"
            )

    def test_high_conversion_boost(self) -> None:
        low = _compute_survival_curve(0.01, {}, benchmark_cr=0.05)
        high = _compute_survival_curve(0.10, {}, benchmark_cr=0.05)
        # Higher conversion should produce higher survival at day 30
        assert high[2] > low[2]

    def test_retention_architect_data_overrides(self) -> None:
        # Use a high conversion rate so day 7 survival is high enough that
        # a day 30 override of 0.50 doesn't violate monotonicity.
        retention_data = {
            "day30_survival": {"actual": 0.50, "benchmark": 0.32, "delta": 0.18, "severity": "INFO"},
        }
        curve = _compute_survival_curve(0.10, retention_data, benchmark_cr=0.05)
        # Day 30 should be overridden to 0.50
        assert abs(curve[2] - 0.50) < 0.001

    def test_curve_values_in_range(self) -> None:
        curve = _compute_survival_curve(0.05, {}, benchmark_cr=0.05)
        for v in curve:
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Churn risk
# ---------------------------------------------------------------------------

class TestChurnRisk:
    def test_critical_risk(self) -> None:
        assert _churn_risk_label(0.05) == "CRITICAL"
        assert _churn_risk_label(0.07) == "CRITICAL"

    def test_high_risk(self) -> None:
        assert _churn_risk_label(0.10) == "HIGH"
        assert _churn_risk_label(0.14) == "HIGH"

    def test_medium_risk(self) -> None:
        assert _churn_risk_label(0.20) == "MEDIUM"
        assert _churn_risk_label(0.24) == "MEDIUM"

    def test_low_risk(self) -> None:
        assert _churn_risk_label(0.30) == "LOW"
        assert _churn_risk_label(0.50) == "LOW"

    def test_risk_score_bounded(self) -> None:
        for d30 in [0.0, 0.1, 0.2, 0.3, 0.5]:
            score = _churn_risk_score(d30)
            assert 0.0 <= score <= 1.0

    def test_risk_score_inversely_correlated(self) -> None:
        low = _churn_risk_score(0.50)
        high = _churn_risk_score(0.05)
        assert high > low


# ---------------------------------------------------------------------------
# build_cohort_retention
# ---------------------------------------------------------------------------

class TestBuildCohortRetention:
    def test_basic_projection(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert isinstance(result, CohortRetentionOut)
        assert result.simulation_id == 1
        assert result.project_id == 2
        assert result.status == "COMPLETED"
        assert result.overall_conversion == 0.05
        assert len(result.cluster_profiles) == 4
        assert len(result.segment_summary) >= 1

    def test_cluster_profiles_structure(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        for p in result.cluster_profiles:
            assert isinstance(p, ClusterRetentionProfile)
            assert p.cluster_id in BREAKDOWN
            assert 0.0 <= p.conversion_rate <= 1.0
            assert len(p.retention_curve) == len(RETENTION_DAYS)
            assert p.churn_risk in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            assert p.ltv_score >= 0.0

    def test_retention_curve_points(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        for p in result.cluster_profiles:
            for point in p.retention_curve:
                assert isinstance(point, RetentionCurvePoint)
                assert point.day in RETENTION_DAYS
                assert 0.0 <= point.survival_rate <= 1.0
                assert 0.0 <= point.cumulative_churn <= 1.0
                assert point.active_users >= 0

    def test_best_worst_clusters(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert result.best_retention_cluster != ""
        assert result.worst_retention_cluster != ""
        # Best should have higher day30 survival than worst
        best = next(p for p in result.cluster_profiles if p.cluster_id == result.best_retention_cluster)
        worst = next(p for p in result.cluster_profiles if p.cluster_id == result.worst_retention_cluster)
        assert best.day30_survival >= worst.day30_survival

    def test_highest_churn_stage(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert result.highest_churn_stage != ""
        assert result.highest_churn_stage.startswith("day")

    def test_market_survival_rates(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert 0.0 <= result.market_day30_survival <= 1.0
        assert 0.0 <= result.market_day90_survival <= 1.0
        assert 0.0 <= result.market_day365_survival <= 1.0
        # Day 30 should be >= day 90 (monotonic at market level)
        assert result.market_day30_survival >= result.market_day90_survival

    def test_churn_trigger_distribution(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert len(result.churn_trigger_distribution) >= 1
        total = sum(result.churn_trigger_distribution.values())
        assert total == len(BREAKDOWN)

    def test_reengagement_viable(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert isinstance(result.reengagement_viable, bool)

    def test_recommendations_generated(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert len(result.recommendations) >= 1
        for rec in result.recommendations:
            assert isinstance(rec, str)
            assert len(rec) > 10

    def test_retention_findings_used(self) -> None:
        findings = [
            _retention_finding("metro_power_professional", "day30_survival", 0.50, 0.32),
            _retention_finding("tier2_price_sensitive_pragmatist", "day30_survival", 0.10, 0.32, "CRITICAL"),
        ]
        result = build_cohort_retention(
            _results(cr=0.05, domain_findings=findings),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert result.meta["retention_findings_used"] == 2
        # Metro should have day30 = 0.50 (overridden)
        metro = next(p for p in result.cluster_profiles if p.cluster_id == "metro_power_professional")
        assert abs(metro.day30_survival - 0.50) < 0.001
        # Tier-2 should have day30 = 0.10
        tier2 = next(p for p in result.cluster_profiles if p.cluster_id == "tier2_price_sensitive_pragmatist")
        assert abs(tier2.day30_survival - 0.10) < 0.001

    def test_empty_results(self) -> None:
        result = build_cohort_retention(
            {},
            simulation_id=1,
            project_id=2,
        )
        assert result.overall_conversion == 0.0
        assert len(result.cluster_profiles) == 0
        assert result.best_retention_cluster == ""
        assert result.worst_retention_cluster == ""

    def test_json_string_results(self) -> None:
        import json
        raw = json.dumps(_results(cr=0.05))
        result = build_cohort_retention(
            raw,
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert result.overall_conversion == 0.05
        assert len(result.cluster_profiles) == 4

    def test_ltv_estimate_positive(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
            aov=999.0,
        )
        for p in result.cluster_profiles:
            if p.day30_survival > 0:
                assert p.ltv_estimate >= 0.0

    def test_segment_summary_structure(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        for seg in result.segment_summary:
            assert seg.segment in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            assert seg.cluster_count >= 1
            assert 0.0 <= seg.mean_day30_survival <= 1.0

    def test_limit_truncation(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
            limit=2,
        )
        assert len(result.cluster_profiles) == 2

    def test_cluster_summaries_agent_counts(self) -> None:
        summaries = [
            {"cluster_id": "metro_power_professional", "agents_assigned": 2000, "agents_converted": 160, "conversion_rate": 0.08},
            {"cluster_id": "tier2_price_sensitive_pragmatist", "agents_assigned": 1500, "agents_converted": 30, "conversion_rate": 0.02},
        ]
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_summaries=summaries,
            cluster_registry=REGISTRY,
        )
        metro = next(p for p in result.cluster_profiles if p.cluster_id == "metro_power_professional")
        assert metro.agents_converted == 160

    def test_meta_fields(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert "generated_at" in result.meta
        assert "retention_days" in result.meta
        assert "benchmark_cr" in result.meta
        assert "cluster_count" in result.meta
        assert "retention_findings_used" in result.meta

    def test_product_type_and_failure_domain(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05, product_type="saas"),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        assert result.product_type_detected == "saas"
        assert result.primary_failure_domain == "unknown"

    def test_schema_round_trip(self) -> None:
        result = build_cohort_retention(
            _results(cr=0.05),
            simulation_id=1,
            project_id=2,
            cluster_registry=REGISTRY,
        )
        dumped = result.model_dump()
        assert dumped["simulation_id"] == 1
        assert isinstance(dumped["cluster_profiles"], list)
        assert isinstance(dumped["segment_summary"], list)
        assert isinstance(dumped["recommendations"], list)
        assert isinstance(dumped["churn_trigger_distribution"], dict)

    def test_high_conversion_clusters_low_churn_risk(self) -> None:
        breakdown = {
            "high_cr_cluster": 0.15,
            "low_cr_cluster": 0.01,
        }
        registry = {
            "high_cr_cluster": {"name": "High CR", "population_weight": 0.20},
            "low_cr_cluster": {"name": "Low CR", "population_weight": 0.15},
        }
        results = {
            "population_weighted_conversion": 0.05,
            "conversion_rate": 0.05,
            "total_agents": 10000,
            "converted": 500,
            "product_type_detected": "saas",
            "cluster_breakdown": breakdown,
        }
        result = build_cohort_retention(
            results,
            simulation_id=1,
            project_id=2,
            cluster_registry=registry,
        )
        high = next(p for p in result.cluster_profiles if p.cluster_id == "high_cr_cluster")
        low = next(p for p in result.cluster_profiles if p.cluster_id == "low_cr_cluster")
        assert high.day30_survival > low.day30_survival
        # High-CR cluster should have lower churn risk than low-CR cluster
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        assert risk_order[high.churn_risk] >= risk_order[low.churn_risk]
