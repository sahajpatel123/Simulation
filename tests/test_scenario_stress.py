from __future__ import annotations

from app.simulation.scenario_stress import ScenarioStressAnalyzer, ScenarioStressResult


def test_scenario_stress_analyzer_happy_path() -> None:
    analyzer = ScenarioStressAnalyzer()
    cluster_breakdown = {
        "metro_power_professional": 0.12,
        "tier3_first_time_app_user": 0.02,
        "student_freelancer": 0.01,
    }
    cluster_registry = [
        {"cluster_id": "metro_power_professional", "name": "Metro Power Professional", "population_weight": 0.5},
        {"cluster_id": "tier3_first_time_app_user", "name": "Tier 3 First-time User", "population_weight": 0.3},
        {"cluster_id": "student_freelancer", "name": "Student Freelancer", "population_weight": 0.2},
    ]
    domain_findings = [
        {"domain": "Pricing", "issue": "High price sensitivity"},
    ]

    result: ScenarioStressResult = analyzer.analyze(
        simulation_id=42,
        base_conversion_rate=0.068,
        cluster_breakdown=cluster_breakdown,
        cluster_registry=cluster_registry,
        domain_findings=domain_findings,
        product_type="saas",
    )

    assert result.simulation_id == 42
    assert result.base_conversion_rate == 0.068
    assert 0.0 <= result.overall_resilience_score <= 100.0
    assert len(result.scenario_impacts) == 4

    keys = {imp.scenario_key for imp in result.scenario_impacts}
    assert keys == {"RECESSION", "PRICE_WAR", "VIRAL_CATALYST", "CHANNEL_BOTTLENECK"}

    # Dictionary conversion verification
    data = analyzer.to_dict(result)
    assert data["simulation_id"] == 42
    assert "scenario_impacts" in data
    assert len(data["scenario_impacts"]) == 4


def test_scenario_stress_analyzer_resilience_score_calculation() -> None:
    analyzer = ScenarioStressAnalyzer()
    cluster_breakdown = {"metro_power_professional": 0.10}
    cluster_registry = [{"cluster_id": "metro_power_professional", "population_weight": 1.0}]

    result = analyzer.analyze(
        simulation_id=1,
        base_conversion_rate=0.10,
        cluster_breakdown=cluster_breakdown,
        cluster_registry=cluster_registry,
        domain_findings=[],
        product_type="hardware",
    )

    assert isinstance(result.overall_resilience_score, float)
    assert result.most_vulnerable_scenario != ""
    assert result.most_resilient_scenario != ""
