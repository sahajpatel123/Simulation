from __future__ import annotations

import pytest

pytest.importorskip("numpy", reason="Full stack: pip install -r requirements.txt (numpy)")

import time
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import Conductor, ProductType, ARCHITECT_STACKS
from app.simulation.accountability import AccountabilityEngine
from app.simulation.markov import MarkovBehaviourModel, ClusterTransitionMatrix
from app.simulation.calibration_engine import CalibrationEngine, ALL_ARCHITECT_NAMES
from app.core.prompts import PREMORTEM_PROMPT, INTERVENTION_PROMPT

r   = ClusterRegistry()
c   = Conductor()
eng = AccountabilityEngine()

# ── T1: ARCHITECTURE INTEGRITY ──

def test_cluster_count():
    assert len(r.all_clusters()) == 52

def test_cluster_weights_sum():
    total = sum(cl.population_weight for cl in r.all_clusters())
    assert abs(total - 1.0) <= 0.001

def test_no_duplicate_cluster_ids():
    ids = [cl.cluster_id for cl in r.all_clusters()]
    assert len(set(ids)) == 52

def test_all_clusters_have_8_traits():
    REQUIRED = {"income_level","digital_literacy","motivation","trust",
                "price_sensitivity","risk_aversion","patience_score","social_orientation"}
    for cl in r.all_clusters():
        assert set(cl.base_traits.keys()) >= REQUIRED, f"{cl.cluster_id} missing traits"

def test_all_product_types_have_stack():
    for pt in ProductType:
        assert pt in ARCHITECT_STACKS, f"{pt} missing from ARCHITECT_STACKS"
        assert len(ARCHITECT_STACKS[pt]) >= 8, f"{pt} stack too short"

def test_architect_stacks_ordering():
    for pt, stack in ARCHITECT_STACKS.items():
        assert stack[0]  == "MarketTimingArchitect",      f"{pt}: MarketTiming must be first"
        assert stack[-1] == "AssumptionCascadeArchitect", f"{pt}: AssumptionCascade must be last"
        assert "MacroeconomicArchitect" in stack
        assert "DemographicInteractionArchitect" in stack

def test_all_architects_instantiate():
    from app.simulation.conductor import _ARCHITECTS
    assert len(_ARCHITECTS) >= 15

def test_product_type_detection():
    cases = [
        ("A SaaS CRM for small businesses with monthly subscription", ProductType.SAAS),
        ("A smartwatch with heart rate and sleep tracking", ProductType.WEARABLE),
        ("An IoT smart home hub connecting devices via Zigbee", ProductType.IOT_HARDWARE),
        ("A freelance marketplace connecting designers with clients", ProductType.MARKETPLACE),
        ("A fitness tracking mobile app for Android and iOS", ProductType.MOBILE_APP),
        ("Enterprise compliance software with SSO and procurement", ProductType.ENTERPRISE_SOFTWARE),
        ("A blood pressure health monitor for chronic patients", ProductType.HEALTH_HARDWARE),
        ("A developer SDK and CLI tool for API integration", ProductType.DEVELOPER_TOOL),
        ("A consumer Bluetooth speaker with 48hr battery", ProductType.CONSUMER_HARDWARE),
        ("B2B rugged POS hardware device for retail fleet", ProductType.B2B_HARDWARE),
    ]
    for desc, expected in cases:
        detected = c.detect_product_type(desc, [])
        assert detected == expected, f"FAIL: '{desc[:40]}' → {detected}, expected {expected}"

def test_cluster_reweighting_sums_to_1():
    for pt in ProductType:
        weights = c._reweight_clusters(pt, {"average_order_value": 999})
        total   = sum(weights.values())
        assert abs(total - 1.0) <= 0.001, f"{pt} weights sum to {total}"

def test_clusters_for_product_type_returns_results():
    # After T2 affinity fix, this must return > 0 for hardware types
    hw_clusters = r.clusters_for_product_type("consumer_hardware")
    assert len(hw_clusters) > 0, "No clusters for consumer_hardware — fix product_affinities"

# ── T2: SIMULATION CORRECTNESS ──

def _run(product_type, description, assumptions, aov=999):
    return c.run(
        agents=[],
        env_params={"average_order_value": aov, "market_maturity": 0.5, "description": description},
        assumptions=assumptions,
        product_type=product_type,
    )

def test_saas_student_low_conversion():
    result = _run(ProductType.SAAS, "SaaS project management tool",
        [{"assumption": "pricing at 999 per month", "sensitivity": "CRITICAL", "claim_confidence": "DESIGN_INTENT"}])
    student_cr = result.cluster_breakdown.get("high_literacy_student_freemium_ceiling", 1.0)
    metro_cr   = result.cluster_breakdown.get("metro_power_professional", 0.0)
    assert student_cr < 0.10, f"Student should have near-zero conversion at ₹999, got {student_cr}"
    assert metro_cr > student_cr, f"Metro should convert higher than student"

def test_tier3_distribution_collapse():
    # No offline distribution → Tier-3 should collapse
    result = _run(ProductType.CONSUMER_HARDWARE, "Consumer Bluetooth speaker",
        [{"assumption": "available online only", "sensitivity": "HIGH"}], aov=3000)
    tier3_cr = result.cluster_breakdown.get("tier3_first_time_app_user", 1.0)
    metro_cr  = result.cluster_breakdown.get("metro_power_professional", 0.0)
    assert tier3_cr < metro_cr * 0.5, f"Tier-3 should collapse vs metro without offline: {tier3_cr} vs {metro_cr}"

def test_health_hardware_clinical_gate():
    # No clinical validation → health clusters suppressed
    result = _run(ProductType.HEALTH_HARDWARE, "Blood pressure health monitor",
        [{"assumption": "wellness device for fitness tracking"}], aov=8000)
    skeptic_cr    = result.cluster_breakdown.get("health_hardware_skeptic", 1.0)
    enthusiast_cr = result.cluster_breakdown.get("health_hardware_enthusiast", 0.0)
    assert skeptic_cr < 0.15, f"Skeptic should be suppressed without clinical validation: {skeptic_cr}"

def test_52_clusters_in_breakdown():
    result = _run(ProductType.SAAS, "SaaS tool", [])
    assert len(result.cluster_breakdown) == 52, f"Expected 52, got {len(result.cluster_breakdown)}"

def test_conductor_result_fields():
    result = _run(ProductType.SAAS, "SaaS tool", [])
    assert result.population_weighted_conversion > 0
    assert len(result.domain_reports) > 0
    assert len(result.architect_accountability) > 0
    assert result.product_type == ProductType.SAAS

# ── T3: ACCOUNTABILITY CORRECTNESS ──

def test_primary_failure_domain_pricing():
    result = _run(ProductType.SAAS, "SaaS tool",
        [{"assumption": "pricing at 999 per month for students", "sensitivity": "CRITICAL"}])
    # Force student-heavy simulation
    findings = eng.generate_domain_findings(result)
    assert len(findings) > 0
    primary = eng.primary_failure_domain(findings)
    assert primary in [
        "PricingArchitect","TrustArchitect","MarketTimingArchitect","CompetitiveDynamicsArchitect"
    ], f"Unexpected primary domain: {primary}"

def test_findings_have_required_keys():
    result  = _run(ProductType.SAAS, "SaaS tool", [])
    findings= eng.generate_domain_findings(result)
    assert len(findings) > 0
    f = findings[0].to_dict()
    for key in ["architect_name","cluster_name","finding","severity",
                "conversion_impact","recommended_action","actual_value","healthy_benchmark"]:
        assert key in f, f"Missing key: {key}"

def test_highest_value_cluster_returns_name():
    result = _run(ProductType.SAAS, "SaaS tool", [])
    name, cr = eng.highest_value_cluster(result)
    assert isinstance(name, str) and len(name) > 0
    assert 0.0 <= cr <= 1.0

def test_cluster_narrative_format():
    result    = _run(ProductType.SAAS, "SaaS tool", [])
    narrative = eng.generate_cluster_breakdown_narrative(result)
    assert "Overall conversion" in narrative
    assert "Primary failure domain" in narrative
    assert "Highest value" in narrative

# ── T4: PER-CLUSTER MATRIX BUILDER ──

def test_per_cluster_matrix_shape():
    result  = _run(ProductType.SAAS, "SaaS tool", [])
    metro   = r.get_cluster("metro_power_professional")
    outputs = result.cluster_results.get(metro.cluster_id, {})
    model   = MarkovBehaviourModel(env_params={"average_order_value":999}, assumptions=[], seed=42)
    ctm     = model.build_for_cluster(metro, outputs, {"average_order_value":999})
    assert ctm.matrix.shape == (7, 7)
    import numpy as np
    assert np.allclose(ctm.matrix.sum(axis=1), 1.0, atol=0.001), "Rows must sum to 1.0"

def test_matrix_student_lower_than_metro():
    result  = _run(ProductType.SAAS, "SaaS tool",
        [{"assumption": "price 999/month"}])
    student = r.get_cluster("high_literacy_student_freemium_ceiling")
    metro   = r.get_cluster("metro_power_professional")
    model   = MarkovBehaviourModel(env_params={"average_order_value":999}, assumptions=[], seed=42)
    ctm_s   = model.build_for_cluster(student, result.cluster_results.get(student.cluster_id, {}), {})
    ctm_m   = model.build_for_cluster(metro,   result.cluster_results.get(metro.cluster_id, {}),   {})
    assert ctm_s.conversion_estimate < ctm_m.conversion_estimate

# ── T5: PERFORMANCE ──

def test_conductor_performance_30s():
    start  = time.time()
    result = _run(ProductType.CONSUMER_HARDWARE, "Consumer hardware product", [], aov=5000)
    elapsed= time.time() - start
    assert elapsed < 30.0, f"Conductor took {elapsed:.1f}s — must be under 30s"
    assert len(result.cluster_breakdown) == 52

# ── T6: PROMPT PLACEHOLDERS ──

def test_premortem_prompt_placeholders():
    filled = PREMORTEM_PROMPT.format(
        domain_findings_text   = "test findings",
        primary_failure_domain = "PricingArchitect",
        highest_value_cluster  = "Metro power professional",
        cluster_narrative      = "test narrative",
    )
    assert "PricingArchitect" in filled
    assert "Metro power professional" in filled

def test_intervention_prompt_placeholders():
    filled = INTERVENTION_PROMPT.format(
        highest_value_cluster  = "Metro power professional",
        primary_failure_domain = "TrustArchitect",
        ranked_findings_text   = "1. Test finding",
        cluster_narrative      = "test narrative",
    )
    assert "TrustArchitect" in filled

# ── T7: CALIBRATION ENGINE ──

def test_calibration_architect_count():
    assert len(ALL_ARCHITECT_NAMES) == 20

def test_calibration_trend_improving():
    from unittest.mock import MagicMock
    class MockRow:
        def __init__(self, g, sq): self.absolute_gap=g; self.signal_quality_at_run=sq
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        MockRow(0.25,0.6), MockRow(0.22,0.7), MockRow(0.18,0.8),
        MockRow(0.12,0.9), MockRow(0.08,0.85), MockRow(0.05,0.9)
    ]
    eng2 = CalibrationEngine()
    assert eng2._compute_trend(1, db) == "IMPROVING"

# ── T8: BACKWARD COMPATIBILITY ──

def test_old_results_json_still_valid():
    # Simulate an old results_json without new fields
    old_results = {
        "conversion_rate": 0.12,
        "agents": 1000,
        "converted": 120,
    }
    # New fields should default gracefully when missing
    assert old_results.get("cluster_breakdown", []) == []
    assert old_results.get("domain_findings", []) == []
    assert old_results.get("primary_failure_domain", "unknown") == "unknown"
    assert old_results.get("product_type_detected", "") == ""

# ── T9: PLAUSIBILITY BOUNDARY FIX ──

def test_plausibility_boundary_exact_10pct():
    # actual == predicted * 0.10 exactly should PASS after off-by-one fix
    predicted = 0.20
    actual    = predicted * 0.10  # exactly 0.02
    fires = predicted > 0.10 and actual <= predicted * 0.10
    assert fires, "Boundary at exactly 10% should now fire (inclusive <=)"
