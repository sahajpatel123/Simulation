"""
Tests for ``app.simulation.architects.sustainability`` — SustainabilityArchitect.

Covers claim detection, credibility / greenwashing risk, ESG affinity,
green-premium friction, conversion lift, Markov transition overrides,
generate_report() rollups, and conductor / calibration registration.
Pure-compute tests — no DB, no LLM, no network.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.architects.sustainability import SustainabilityArchitect
from app.simulation.clusters.registry import ClusterRegistry


def _get_cluster(cluster_id: str):
    return ClusterRegistry().get_cluster(cluster_id)


_CLAIM_WITH_EVIDENCE = [
    {"text": "Packaging is certified compostable and made from recycled materials"}
]
_CLAIM_WITHOUT_EVIDENCE = [{"text": "Eco-friendly packaging"}]


# ── Identity / registration ───────────────────────────────────────────


def test_name_is_sustainability_architect():
    arch = SustainabilityArchitect()
    assert arch.name == "SustainabilityArchitect"


def test_active_for_all_product_types():
    # Empty product_types means the conductor runs this architect for every
    # product category (see Conductor's pt_ok check).
    arch = SustainabilityArchitect()
    assert arch.product_types == []
    assert isinstance(arch, BaseArchitect)


# ── compute() output shape ────────────────────────────────────────────


def test_compute_returns_valid_architect_output():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    assert isinstance(out, ArchitectOutput)
    assert out.architect_name == "SustainabilityArchitect"
    assert out.cluster_id == "metro_power_professional"
    for key in (
        "sustainability_signal",
        "esg_affinity",
        "green_premium_tolerance",
        "conversion_lift",
        "premium_friction",
        "claim_credibility",
    ):
        assert key in out.metrics, f"missing metric {key}"
        assert 0.0 <= out.metrics[key] <= 1.0
    assert out.metrics["conversion_lift"] <= 0.30
    assert isinstance(out.flags, dict)
    assert isinstance(out.narrative_findings, list) and out.narrative_findings
    assert out.severity in ("INFO", "WARNING", "CRITICAL")


# ── Neutral behaviour without claims ──────────────────────────────────


def test_no_claims_is_neutral():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    assert out.metrics["sustainability_signal"] == 0.0
    assert out.metrics["conversion_lift"] == 0.0
    assert out.metrics["premium_friction"] == 0.0
    assert out.flags["sustainability_positioned"] is False
    assert out.flags["greenwashing_risk"] is False
    assert out.severity == "INFO"
    # A product that never mentions sustainability must not perturb the funnel.
    assert arch.transition_overrides(out) == {}


# ── Claim detection and credibility ───────────────────────────────────


def test_evidence_backed_claims_raise_signal_and_credibility():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    vague = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITHOUT_EVIDENCE,
        env_params={},
    )
    backed = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    assert backed.metrics["sustainability_signal"] > vague.metrics["sustainability_signal"]
    assert backed.metrics["claim_credibility"] == 1.0
    assert vague.metrics["claim_credibility"] == 0.25
    assert backed.metrics["conversion_lift"] > vague.metrics["conversion_lift"]


def test_greenwashing_risk_without_evidence():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    vague = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITHOUT_EVIDENCE,
        env_params={},
    )
    backed = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    assert vague.flags["greenwashing_risk"] is True
    assert vague.severity == "WARNING"
    assert backed.flags["greenwashing_risk"] is False


def test_price_sensitive_low_income_cluster_has_premium_friction():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("low_literacy_student_passive")
    out = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    assert out.flags["premium_friction"] is True
    assert out.metrics["premium_friction"] >= 0.55
    assert out.severity == "WARNING"


def test_sustainability_weight_env_param_scales_conversion_lift():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    base = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    boosted = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={"sustainability_weight": 2.0},
    )
    assert base.metrics["conversion_lift"] > 0.0
    assert boosted.metrics["conversion_lift"] > base.metrics["conversion_lift"]


# ── Markov transition overrides ───────────────────────────────────────


def test_transition_overrides_only_when_positioned():
    arch = SustainabilityArchitect()
    cluster = _get_cluster("metro_power_professional")
    neutral = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    positioned = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=_CLAIM_WITH_EVIDENCE,
        env_params={},
    )
    overrides = arch.transition_overrides(positioned)
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") in overrides
    assert 0.40 <= overrides[("CONSIDER", "DECIDE")] <= 1.30
    assert 0.05 <= overrides[("DECIDE", "PURCHASE")] <= 0.95
    assert arch.transition_overrides(neutral) == {}


# ── generate_report() ─────────────────────────────────────────────────


def test_generate_report_handles_empty_outputs():
    arch = SustainabilityArchitect()
    report = arch.generate_report([])
    assert isinstance(report, DomainReport)
    assert report.architect_name == "SustainabilityArchitect"
    assert report.affected_cluster_ids == []
    assert report.population_fraction == 0.0
    assert report.conversion_impact == 0.0
    assert report.severity == "INFO"


def test_generate_report_aggregates_clusters():
    arch = SustainabilityArchitect()
    outputs = [
        arch.compute(
            cluster=_get_cluster("metro_power_professional"),
            agent_profile={},
            assumptions=_CLAIM_WITH_EVIDENCE,
            env_params={},
        ),
        arch.compute(
            cluster=_get_cluster("low_literacy_student_passive"),
            agent_profile={},
            assumptions=_CLAIM_WITH_EVIDENCE,
            env_params={},
        ),
        arch.compute(
            cluster=_get_cluster("tier3_first_time_app_user"),
            agent_profile={},
            assumptions=[],
            env_params={},
        ),
    ]
    report = arch.generate_report(outputs)
    assert isinstance(report, DomainReport)
    assert report.conversion_impact > 0.0
    assert "metro_power_professional" in report.affected_cluster_ids
    assert report.population_fraction > 0.0
    assert report.recommended_action
    assert report.severity in ("INFO", "WARNING", "CRITICAL")


def test_generate_report_no_positioned_clusters_is_info():
    arch = SustainabilityArchitect()
    outputs = [
        arch.compute(
            cluster=_get_cluster("tier3_first_time_app_user"),
            agent_profile={},
            assumptions=[],
            env_params={},
        )
    ]
    report = arch.generate_report(outputs)
    assert report.conversion_impact == 0.0
    assert report.severity == "INFO"


# ── Conductor / calibration registration ──────────────────────────────


def test_registered_in_conductor_and_calibration():
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.conductor import ARCHITECT_STACKS, ProductType, _ARCHITECTS

    assert "SustainabilityArchitect" in _ARCHITECTS
    assert "SustainabilityArchitect" in ARCHITECT_STACKS[ProductType.SAAS]
    assert "SustainabilityArchitect" in ARCHITECT_STACKS[ProductType.CONSUMER_HARDWARE]
    for stack in ARCHITECT_STACKS.values():
        assert "SustainabilityArchitect" in stack
    assert "SustainabilityArchitect" in ALL_ARCHITECT_NAMES
