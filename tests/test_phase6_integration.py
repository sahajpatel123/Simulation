from __future__ import annotations

import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("numpy", reason="Full stack: pip install -r requirements.txt (numpy)")
pytest.importorskip("scipy", reason="Full stack: pip install -r requirements.txt (scipy)")
pytest.importorskip("tiktoken", reason="Optional test dep: pip install tiktoken")

import tiktoken

from app.core.prompts import INTERVENTION_PROMPT, PREMORTEM_PROMPT
from app.schemas.simulation import SimulationResultOut
from app.simulation.accountability import AccountabilityEngine
from app.simulation.aggregation import ResultsAggregator
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import ARCHITECT_STACKS, Conductor, _build_architect_registry
from app.simulation.product_type import ProductType
from app.simulation.profiles import AgentProfileGenerator
from app.tasks.simulation_tasks import _funnel_result_from_conductor


REPO_ROOT = Path(__file__).resolve().parents[1]
ENCODING = tiktoken.get_encoding("cl100k_base")


def _positive_assumptions(*extra: str) -> list[dict[str, str]]:
    base = [
        {"text": "known brand established recognized with reviews testimonials and case studies"},
        {"text": "feature complete full featured all features unique differentiated 10x better"},
        {"text": "urgent critical must have problem"},
    ]
    base.extend({"text": item} for item in extra)
    return base


def _run_conductor(
    *,
    product_type: ProductType,
    description: str,
    assumptions: list[dict[str, str]],
    average_order_value: float,
    geography: str = "ALL_INDIA",
    target_segment: str = "B2C",
    age_target: str = "ALL",
    market_maturity: float = 0.55,
    consumer_volume: int = 10_000,
):
    env = {
        "description": description,
        "consumer_volume": consumer_volume,
        "growth_rate_per_month": 0.08,
        "average_order_value": average_order_value,
        "price_sensitivity": 0.55,
        "market_maturity": market_maturity,
        "geography": geography,
        "target_segment": target_segment,
        "age_target": age_target,
    }
    agents = [None] * consumer_volume
    result = Conductor().run(
        agents=agents,
        env_params=env,
        assumptions=assumptions,
        product_type=product_type,
    )
    return env, result


def _git_show(path_at_commit: str, commit: str = "3e3ba4f") -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "show", f"{commit}:{path_at_commit}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None


def _prompt_body(source: str, name: str) -> str:
    match = re.search(rf"{name} = \"\"\"(.*?)\"\"\"", source, re.S)
    assert match is not None, f"{name} not found"
    return match.group(1)


def test_cluster_registry_integrity():
    clusters = ClusterRegistry().all_clusters()
    assert len(clusters) == 52
    assert abs(sum(c.population_weight for c in clusters) - 1.0) < 1e-9


def test_architect_registry_and_product_stacks_integrity():
    registry = _build_architect_registry()
    assert len(registry) == 20
    assert set(ARCHITECT_STACKS) == set(ProductType)
    for product_type, stack in ARCHITECT_STACKS.items():
        assert stack, f"{product_type.value} stack must not be empty"
        for name in stack:
            assert name in registry, f"{name} missing from registry"


def test_detect_product_type_for_ten_descriptions():
    conductor = Conductor()
    cases = {
        "B2B SaaS CRM dashboard for sales teams": ProductType.SAAS,
        "A two-sided marketplace connecting freelance designers with buyers": ProductType.MARKETPLACE,
        "A mobile app for habit tracking on iOS and Android": ProductType.MOBILE_APP,
        "An SDK and CLI for API testing in CI pipelines": ProductType.DEVELOPER_TOOL,
        "Enterprise procurement and compliance platform with SSO": ProductType.ENTERPRISE_SOFTWARE,
        "A bluetooth smart speaker hardware gadget for consumers": ProductType.CONSUMER_HARDWARE,
        "A medical device for blood pressure monitoring with clinical validation": ProductType.HEALTH_HARDWARE,
        "A smart home IoT sensor hub with Matter support": ProductType.IOT_HARDWARE,
        "A smartwatch wearable fitness tracker ring": ProductType.WEARABLE,
        "A ruggedized enterprise kiosk and POS device for fleets": ProductType.B2B_HARDWARE,
    }
    for description, expected in cases.items():
        assert conductor.detect_product_type(description, []) == expected


def test_saas_student_cluster_stays_near_zero_at_rupee_999_while_metro_cluster_is_higher():
    _, result = _run_conductor(
        product_type=ProductType.SAAS,
        description="A SaaS study and productivity dashboard for students",
        assumptions=_positive_assumptions("student study app"),
        average_order_value=999,
        age_target="STUDENT",
        market_maturity=0.55,
    )

    student_rate = result.cluster_breakdown["high_literacy_student_freemium_ceiling"]
    metro_rate = result.cluster_breakdown["metro_power_professional"]
    mid_income_rate = result.cluster_breakdown["urban_mid_income_saas_buyer"]

    assert student_rate <= 0.0030
    assert metro_rate > student_rate
    assert metro_rate > mid_income_rate


def test_hardware_tier3_distribution_collapses_without_offline_channel():
    _, online_only = _run_conductor(
        product_type=ProductType.CONSUMER_HARDWARE,
        description="A premium smart speaker sold online only",
        assumptions=[{"text": "premium smart speaker sold online only"}],
        average_order_value=12_000,
        geography="TIER3",
    )
    _, offline_enabled = _run_conductor(
        product_type=ProductType.CONSUMER_HARDWARE,
        description="A premium smart speaker sold online and offline retail",
        assumptions=[{"text": "premium smart speaker sold online and offline retail store physical distribution tier-2 available"}],
        average_order_value=12_000,
        geography="TIER3",
    )

    tier3_online = online_only.cluster_results["tier3_first_time_app_user"]["DistributionChannelArchitect"]
    tier3_offline = offline_enabled.cluster_results["tier3_first_time_app_user"]["DistributionChannelArchitect"]
    enthusiast_online = online_only.cluster_results["high_income_hardware_enthusiast"]["DistributionChannelArchitect"]

    assert tier3_online.metrics["distribution_accessibility_multiplier"] == 0.3
    assert tier3_online.flags["distribution_kill_shot"] is True
    assert tier3_offline.metrics["distribution_accessibility_multiplier"] == 1.0
    assert enthusiast_online.metrics["distribution_accessibility_multiplier"] == 1.0


def test_health_hardware_clinical_validation_gate_suppresses_non_enthusiast_clusters():
    _, result = _run_conductor(
        product_type=ProductType.HEALTH_HARDWARE,
        description="A wearable fitness tracker for sleep, activity, and wellness insights",
        assumptions=[{"text": "wearable fitness tracker for sleep, activity, and wellness insights"}],
        average_order_value=6_999,
    )

    skeptic = result.cluster_results["health_hardware_skeptic"]["HealthSafetyHardwareArchitect"]
    enthusiast = result.cluster_results["health_hardware_enthusiast"]["HealthSafetyHardwareArchitect"]
    wealthy = result.cluster_results["wealthy_health_conscious_buyer"]["HealthSafetyHardwareArchitect"]

    assert skeptic.metrics["clinical_gate_multiplier"] == 0.05
    assert wealthy.metrics["clinical_gate_multiplier"] == 0.05
    assert enthusiast.metrics["clinical_gate_multiplier"] == 1.0


def test_780_architect_compute_calls_finish_under_30_seconds():
    clusters = ClusterRegistry().all_clusters()
    registry = _build_architect_registry()
    architects = [
        registry["MarketTimingArchitect"],
        registry["CompetitiveDynamicsArchitect"],
        registry["TrustArchitect"],
        registry["PricingArchitect"],
        registry["OnboardingArchitect"],
        registry["FeatureAdoptionArchitect"],
        registry["RetentionArchitect"],
        registry["SupportFrictionArchitect"],
        registry["ViralityArchitect"],
        registry["MacroeconomicArchitect"],
        registry["DemographicInteractionArchitect"],
        registry["AssumptionCascadeArchitect"],
        registry["PurchaseDecisionArchitect"],
        registry["PhysicalSensoryArchitect"],
        registry["DistributionChannelArchitect"],
    ]
    env = {
        "product_type": ProductType.CONSUMER_HARDWARE.value,
        "market_maturity": 0.6,
        "average_order_value": 4_999,
        "geography": "ALL_INDIA",
        "target_segment": "B2C",
        "age_target": "ALL",
    }
    assumptions = _positive_assumptions("offline retail store availability")

    count = 0
    started = time.perf_counter()
    for cluster in clusters:
        for architect in architects:
            architect.compute(cluster, {}, assumptions, env)
            count += 1
    elapsed = time.perf_counter() - started

    assert count == 780
    assert elapsed < 30


def test_full_10000_agent_simulation_finishes_within_render_budget():
    env = {
        "description": "A wearable wellness tracker for sleep and activity insights",
        "consumer_volume": 10_000,
        "growth_rate_per_month": 0.08,
        "average_order_value": 4_999,
        "price_sensitivity": 0.55,
        "market_maturity": 0.6,
        "geography": "ALL_INDIA",
        "target_segment": "B2C",
        "age_target": "ALL",
    }
    assumptions = _positive_assumptions("wearable fitness tracker with sleep and activity insights")

    started = time.perf_counter()
    agents = AgentProfileGenerator().generate_population(
        volume=10_000,
        env_params=env,
        scenario_type="NORMAL",
        seed=123,
    )
    result = Conductor().run(
        agents=agents,
        env_params=env,
        assumptions=assumptions,
        product_type=ProductType.WEARABLE,
    )
    elapsed = time.perf_counter() - started

    assert len(agents) == 10_000
    assert len(result.cluster_results) == 52
    assert elapsed < 300


def test_prompt_token_budgets_are_lower_than_pre_step_48_templates():
    # The historical baseline was authored before the `backend/app/` package
    # layout existed; the legacy path `app/core/prompts.py` is no longer
    # fetchable from the pinned commit, so fall back to the first commit
    # where the canonical `backend/app/core/prompts.py` introduced the
    # prompt constants. Skip when neither source is reachable (e.g. shallow
    # clones without the historical commit).
    for candidate in (
        ("app/core/prompts.py", "3e3ba4f"),
        ("backend/app/core/prompts.py", "a9fcff9"),
    ):
        historical = _git_show(*candidate)
        if historical is not None:
            break
    if historical is None:
        pytest.skip(
            "Historical prompts.py baseline unavailable; token-budget regression "
            "test requires a full clone."
        )
    try:
        old_pre = _prompt_body(historical, "PREMORTEM_PROMPT")
        old_int = _prompt_body(historical, "INTERVENTION_PROMPT")
    except AssertionError:
        pytest.skip(
            "PREMORTEM_PROMPT/INTERVENTION_PROMPT not present in historical baseline."
        )

    current_pre = len(ENCODING.encode(PREMORTEM_PROMPT))
    current_int = len(ENCODING.encode(INTERVENTION_PROMPT))
    old_pre_tokens = len(ENCODING.encode(old_pre))
    old_int_tokens = len(ENCODING.encode(old_int))

    assert current_pre < old_pre_tokens
    assert current_int < old_int_tokens


def test_prompts_include_specific_cluster_and_architect_context():
    findings_text = (
        "- PricingArchitect | High-literacy student with freemium ceiling | "
        "will_pay_probability 0.05 vs benchmark 0.40\n"
        "- TrustArchitect | Metro power professional | "
        "social_proof_met_fraction 0.26 vs benchmark 0.70"
    )
    cluster_narrative = (
        "Metro power professional leads conversion; "
        "high-literacy student with freemium ceiling underperforms at current price."
    )

    premortem = PREMORTEM_PROMPT.format(
        domain_findings_text=findings_text,
        primary_failure_domain="PricingArchitect",
        highest_value_cluster="Metro power professional",
        cluster_narrative=cluster_narrative,
    )
    intervention = INTERVENTION_PROMPT.format(
        highest_value_cluster="Metro power professional",
        primary_failure_domain="PricingArchitect",
        ranked_findings_text=findings_text,
        cluster_narrative=cluster_narrative,
    )

    for prompt in (premortem, intervention):
        assert "PricingArchitect" in prompt
        assert "Metro power professional" in prompt
        assert "High-literacy student with freemium ceiling" in prompt


def test_accountability_marks_pricing_as_primary_failure_for_student_rupee_999_scenario():
    _, result = _run_conductor(
        product_type=ProductType.SAAS,
        description="A SaaS study and productivity dashboard for students",
        assumptions=_positive_assumptions("student study app"),
        average_order_value=999,
        age_target="STUDENT",
        market_maturity=0.55,
    )

    engine = AccountabilityEngine()
    findings = engine.generate_domain_findings(result, total_agents=10_000)
    pricing_findings = [
        f for f in findings
        if f.architect_name == "PricingArchitect" and "student" in f.cluster_id
    ]

    assert engine.primary_failure_domain(findings) == "PricingArchitect"
    assert pricing_findings
    assert any(f.metric_affected == "will_pay_probability" for f in pricing_findings)
    assert all(f.impact_on_overall_conversion > 0 for f in pricing_findings)
    assert all(f.healthy_benchmark > f.actual_value for f in pricing_findings)


def test_results_payload_is_backward_compatible_and_additive():
    env, conductor_result = _run_conductor(
        product_type=ProductType.SAAS,
        description="A SaaS productivity dashboard",
        assumptions=_positive_assumptions(),
        average_order_value=999,
        market_maturity=0.55,
        consumer_volume=1_000,
    )

    funnel_result = _funnel_result_from_conductor(
        conductor_result=conductor_result,
        total_agents=1_000,
        env_params=env,
        seed=37,
        wall_time_seconds=0.1,
    )
    agg_result = ResultsAggregator().aggregate(
        results=[funnel_result],
        base_price=float(env["average_order_value"]),
        price_sensitivity=float(env["price_sensitivity"]),
    )
    results_dict = ResultsAggregator().to_dict(agg_result)
    results_dict["cluster_breakdown"] = conductor_result.cluster_breakdown
    results_dict["domain_findings"] = [
        f.to_dict() for f in AccountabilityEngine().generate_domain_findings(conductor_result, total_agents=1_000)[:10]
    ]
    results_dict["primary_failure_domain"] = "PricingArchitect"
    results_dict["highest_value_cluster"] = {"name": "Metro power professional", "conversion_rate": 0.0038}
    results_dict["architect_accountability"] = conductor_result.architect_accountability
    results_dict["product_type_detected"] = conductor_result.product_type.value
    results_dict["cluster_narrative"] = "Representative narrative."

    legacy_keys = {
        "total_runs",
        "total_agents",
        "mean_conversion_rate",
        "mean_revenue",
        "ci_95",
        "stage_aggregations",
        "worst_drop_off_stage",
        "insights",
    }
    additive_keys = {
        "cluster_breakdown",
        "domain_findings",
        "primary_failure_domain",
        "highest_value_cluster",
        "architect_accountability",
        "product_type_detected",
        "cluster_narrative",
    }

    assert legacy_keys.issubset(results_dict)
    assert additive_keys.issubset(results_dict)

    legacy_schema = SimulationResultOut(
        id=1,
        project_id=1,
        status="COMPLETED",
        consumer_volume=1_000,
        results={"mean_conversion_rate": 0.12},
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert legacy_schema.cluster_breakdown == []
    assert legacy_schema.domain_findings == []
    assert legacy_schema.primary_failure_domain == "unknown"
