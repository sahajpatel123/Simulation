"""Unit tests for CulturalContextArchitect.

Pure-compute tests — no DB, no LLM, no network. Uses real clusters from
the in-code ClusterRegistry so the trait dictionaries are realistic.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect
from app.simulation.architects.cultural_context import CulturalContextArchitect
from app.simulation.clusters.registry import ClusterRegistry


def _get_cluster(cluster_id: str):
    return ClusterRegistry().get_cluster(cluster_id)


# ── Identity / registration ───────────────────────────────────────────


def test_name_is_cultural_context_architect():
    arch = CulturalContextArchitect()
    assert arch.name == "CulturalContextArchitect"


def test_active_for_all_product_types():
    arch = CulturalContextArchitect()
    assert set(arch.product_types) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ── compute() output shape ────────────────────────────────────────────


def test_compute_returns_valid_architect_output():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    assert isinstance(out, ArchitectOutput)
    assert out.architect_name == "CulturalContextArchitect"
    assert out.cluster_id == "metro_power_professional"
    for key in (
        "cultural_alignment_score",
        "language_accessibility_score",
        "family_influence_factor",
        "seasonal_relevance_score",
        "local_brand_trust",
        "religious_sensitivity_risk",
        "overall_cultural_correction",
    ):
        assert key in out.metrics, f"missing metric {key}"
        assert 0.0 <= out.metrics[key] <= 2.0
    assert isinstance(out.flags, dict)
    assert isinstance(out.narrative_findings, list)
    assert out.severity in ("INFO", "WARNING", "CRITICAL")


# ── Language accessibility detection ─────────────────────────────────


def test_metro_high_literacy_has_no_language_barrier():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    assert out.flags["language_barrier_detected"] is False
    assert out.metrics["language_accessibility_score"] >= 0.55


def test_tier3_low_literacy_triggers_language_barrier():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("tier3_first_time_app_user")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    assert out.flags["language_barrier_detected"] is True
    assert out.metrics["language_accessibility_score"] < 0.55


def test_regional_language_assumption_lifts_accessibility():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("tier3_first_time_app_user")
    no_support = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    with_support = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "Supports Hindi and Tamil regional language UI"}],
        env_params={},
    )
    assert (
        with_support.metrics["language_accessibility_score"]
        > no_support.metrics["language_accessibility_score"]
    )


# ── Festival / religious assumption detection ────────────────────────


def test_festival_keywords_raise_seasonal_score():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    no_fest = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "A B2B SaaS dashboard for SMBs"}],
        env_params={},
    )
    fest = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "Launch timed for Diwali wedding gifting season"}],
        env_params={},
    )
    assert (
        fest.metrics["seasonal_relevance_score"]
        > no_fest.metrics["seasonal_relevance_score"]
    )


def test_religious_keywords_trigger_sensitivity_concern():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[
            {"text": "Vegetarian, halal-friendly, aligned with Hindu rituals"}
        ],
        env_params={},
    )
    assert out.flags["religious_sensitivity_concern"] is True
    assert out.metrics["religious_sensitivity_risk"] > 0.5


# ── Dependency map integration ───────────────────────────────────────


def test_problem_urgency_dependency_dampens_seasonal_penalty():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    base = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "Diwali seasonal gifting launch"}],
        env_params={},
    )
    urgent = arch.compute(
        cluster=cluster,
        agent_profile={"problem_urgency_intensity": 0.95},
        assumptions=[{"text": "Diwali seasonal gifting launch"}],
        env_params={},
    )
    assert (
        urgent.metrics["seasonal_relevance_score"]
        >= base.metrics["seasonal_relevance_score"] - 0.001
    )


# ── transition_overrides ─────────────────────────────────────────────


def test_transition_overrides_contain_expected_keys():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={}
    )
    overrides = arch.transition_overrides(out)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") in overrides
    for v in overrides.values():
        assert 0.05 <= v <= 1.30


def test_transition_overrides_compress_for_religious_sensitivity():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    benign = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "A standard productivity app"}],
        env_params={},
    )
    risky = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "Halal certified, vegetarian, Hindu festival aligned"}],
        env_params={},
    )
    benign_decide = benign.metrics["cultural_alignment_score"]
    risky_decide  = risky.metrics["cultural_alignment_score"]
    # Religious sensitivity should not raise decide→purchase replacement
    assert (
        arch.transition_overrides(risky)[("DECIDE", "PURCHASE")]
        <= arch.transition_overrides(benign)[("DECIDE", "PURCHASE")] + 0.05
    )


# ── generate_report() ─────────────────────────────────────────────────


def test_generate_report_handles_empty_outputs():
    arch = CulturalContextArchitect()
    rep = arch.generate_report([])
    assert rep.architect_name == "CulturalContextArchitect"
    assert rep.severity == "INFO"
    assert rep.affected_cluster_ids == []


def test_generate_report_aggregates_across_real_clusters():
    arch = CulturalContextArchitect()
    cluster_ids = [
        "metro_power_professional",
        "tier3_first_time_app_user",
        "high_literacy_student_freemium_ceiling",
    ]
    outputs = [
        arch.compute(
            cluster=_get_cluster(cid),
            agent_profile={},
            assumptions=[],
            env_params={},
        )
        for cid in cluster_ids
    ]
    rep = arch.generate_report(outputs)
    assert rep.architect_name == "CulturalContextArchitect"
    assert isinstance(rep.affected_cluster_ids, list)
    assert rep.severity in ("INFO", "WARNING", "CRITICAL")
    # The tier3 cluster should appear in the affected list when flagged
    if outputs[1].flags["language_barrier_detected"]:
        assert "tier3_first_time_app_user" in rep.affected_cluster_ids


# ── Polish iteration: env geography integration ─────────────────────


def test_geo_target_alignment_metric_present():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    out = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={},
    )
    assert "geo_target_alignment" in out.metrics
    assert 0.0 <= out.metrics["geo_target_alignment"] <= 1.0


def test_env_geo_mismatch_reduces_cultural_alignment():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    base = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={},
    )
    mismatch = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[],
        env_params={"geography": "TIER3_RURAL"},
    )
    assert (
        mismatch.metrics["cultural_alignment_score"]
        < base.metrics["cultural_alignment_score"]
    )
    assert (
        mismatch.metrics["geo_target_alignment"]
        < base.metrics["geo_target_alignment"]
    )


def test_env_geo_match_preserves_alignment():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    base = arch.compute(
        cluster=cluster, agent_profile={}, assumptions=[], env_params={},
    )
    match = arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[],
        env_params={"geography": "METRO"},
    )
    assert (
        match.metrics["cultural_alignment_score"]
        > base.metrics["cultural_alignment_score"]
    )
    assert (
        match.metrics["geo_target_alignment"]
        > base.metrics["geo_target_alignment"]
    )


# ── Polish iteration: registry-weighted reporting ───────────────────


def test_generate_report_uses_real_population_weights():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("tier3_first_time_app_user")
    outputs = [arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[{"text": "Hindi regional language support"}],
        env_params={},
    )]
    rep = arch.generate_report(outputs)
    registry = ClusterRegistry()
    total_weight = sum(c.population_weight for c in registry.all_clusters())
    expected = round(cluster.population_weight / total_weight, 4)
    assert rep.population_fraction == expected
    # Must not silently fall back to the old flat 0.04-per-cluster heuristic
    assert rep.population_fraction != 0.04


def test_generate_report_recommendation_branches_on_language_barrier():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("tier3_first_time_app_user")
    outputs = [arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[],
        env_params={},
    )]
    rep = arch.generate_report(outputs)
    rec = rep.recommended_action.lower()
    assert "hindi" in rec or "regional language" in rec


def test_generate_report_recommendation_branches_on_religious_sensitivity():
    arch = CulturalContextArchitect()
    cluster = _get_cluster("metro_power_professional")
    outputs = [arch.compute(
        cluster=cluster,
        agent_profile={},
        assumptions=[
            {"text": "Halal certified vegetarian Hindu-aligned product"}
        ],
        env_params={},
    )]
    rep = arch.generate_report(outputs)
    rec = rep.recommended_action.lower()
    assert "vegetarian" in rec or "halal" in rec
