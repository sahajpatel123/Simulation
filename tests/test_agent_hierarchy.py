"""
Tests for ``app.simulation.agent_hierarchy`` — pure-Python routing logic.

The router drives UI simulation cost by selecting MICRO vs WORKER vs
SUPERVISOR tiers per cluster. Locks down:
  * explicit map priority (SUPERVISOR / MICRO sets)
  * trait-based fallback (low literacy / high literacy + patience)
  * keyword fallback (cluster id substring matching)
  * final default to WORKER
  * batch routing & tier summary invariants
  * needs_browser / is_micro helpers
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Explicit cluster maps
# ---------------------------------------------------------------------------


def test_supervisor_explicit_clusters_route_to_supervisor() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        SUPERVISOR_CLUSTERS,
    )

    router = AgentHierarchyRouter()
    for cid in SUPERVISOR_CLUSTERS:
        decision = router.route(cid)
        assert decision.cluster_id == cid
        assert decision.tier == AgentTier.SUPERVISOR, cid
        # High confidence for explicit mapping.
        assert decision.confidence == 0.95


def test_micro_explicit_clusters_route_to_micro() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        MICRO_CLUSTERS,
    )

    router = AgentHierarchyRouter()
    for cid in MICRO_CLUSTERS:
        decision = router.route(cid)
        assert decision.cluster_id == cid
        assert decision.tier == AgentTier.MICRO, cid
        assert decision.confidence == 0.92


def test_supervisor_and_micro_sets_are_disjoint() -> None:
    from app.simulation.agent_hierarchy import MICRO_CLUSTERS, SUPERVISOR_CLUSTERS

    assert SUPERVISOR_CLUSTERS & MICRO_CLUSTERS == set()


# ---------------------------------------------------------------------------
# Trait-based fallback
# ---------------------------------------------------------------------------


def test_low_literacy_trait_routes_to_micro() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    # cluster "fictional_unknown" is not in either explicit set; passes through
    # to the trait fallback.
    prof = {"digital_literacy": 0.10, "patience_score": 0.5}
    decision = router.route("fictional_unknown", agent_profile=prof)
    assert decision.tier == AgentTier.MICRO
    assert decision.confidence == 0.80
    assert "0.10" in decision.reason or "0.1" in decision.reason


def test_low_patience_trait_routes_to_micro() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    prof = {"digital_literacy": 0.6, "patience_score": 0.1}
    decision = router.route("fictional_unknown_two", agent_profile=prof)
    assert decision.tier == AgentTier.MICRO


def test_high_literacy_and_patience_routes_to_worker() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    prof = {"digital_literacy": 0.9, "patience_score": 0.9}
    decision = router.route("fictional_unknown_three", agent_profile=prof)
    assert decision.tier == AgentTier.WORKER
    assert decision.confidence == 0.85


def test_mid_trait_profile_falls_through_to_keyword_fallback() -> None:
    """Mid traits (no strong signal) should hit the keyword/default path."""
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    prof = {"digital_literacy": 0.5, "patience_score": 0.5}
    # Cluster id containing "tier3" triggers keyword MICRO.
    decision = router.route("some_tier3_cluster", agent_profile=prof)
    assert decision.tier == AgentTier.MICRO
    assert "tier3" in decision.reason.lower() or "bounce" in decision.reason.lower()


def test_unrecognised_cluster_with_no_profile_defaults_to_worker() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    decision = router.route("completely_unmapped_id")
    assert decision.tier == AgentTier.WORKER
    assert decision.confidence == 0.60


def test_unrecognised_cluster_with_neutral_profile_keyword_match() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    prof = {"digital_literacy": 0.5, "patience_score": 0.5}
    decision = router.route("smb_owner_dave", agent_profile=prof)
    assert decision.tier == AgentTier.SUPERVISOR
    assert decision.confidence == 0.75


def test_explicit_map_takes_priority_over_traits() -> None:
    """Even with low-literacy profile, a SUPERVISOR cluster stays SUPERVISOR."""
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    cid = "senior_enterprise_decision_maker"  # in SUPERVISOR_CLUSTERS
    prof = {"digital_literacy": 0.05, "patience_score": 0.01}
    decision = router.route(cid, agent_profile=prof)
    assert decision.tier == AgentTier.SUPERVISOR
    assert decision.confidence == 0.95


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------


def test_keyword_supervisor_triggers_for_enterprise_substring() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    # No profile / no explicit id → falls through to keyword detection.
    decision = router.route("random_enterprise_b2b_xyz")
    assert decision.tier == AgentTier.SUPERVISOR


def test_keyword_micro_triggers_for_low_literacy_substring() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    decision = router.route("low_literacy_anything_xyz")
    assert decision.tier == AgentTier.MICRO


def test_keyword_micro_triggers_for_impulsive_substring() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    decision = router.route("impulsive_shopper_q")
    assert decision.tier == AgentTier.MICRO


def test_case_insensitive_keyword_match() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    decision = router.route("HEALTH_enthusiast")  # upper case
    assert decision.tier == AgentTier.SUPERVISOR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_needs_browser_true_for_worker_and_supervisor() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        AgentRoutingDecision,
    )

    router = AgentHierarchyRouter()
    for tier in (AgentTier.WORKER, AgentTier.SUPERVISOR):
        d = AgentRoutingDecision(cluster_id="x", tier=tier, reason="", confidence=1.0)
        assert router.needs_browser(d) is True


def test_needs_browser_false_for_micro() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        AgentRoutingDecision,
    )

    router = AgentHierarchyRouter()
    d = AgentRoutingDecision(
        cluster_id="x", tier=AgentTier.MICRO, reason="", confidence=1.0
    )
    assert router.needs_browser(d) is False


def test_is_micro_predicate() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        AgentRoutingDecision,
    )

    router = AgentHierarchyRouter()
    micro = AgentRoutingDecision(
        cluster_id="x", tier=AgentTier.MICRO, reason="", confidence=1.0
    )
    worker = AgentRoutingDecision(
        cluster_id="x", tier=AgentTier.WORKER, reason="", confidence=1.0
    )
    assert router.is_micro(micro) is True
    assert router.is_micro(worker) is False


# ---------------------------------------------------------------------------
# Batch + summary
# ---------------------------------------------------------------------------


def test_route_batch_iterates_per_cluster() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    decisions = router.route_batch(
        [
            "senior_enterprise_decision_maker",
            "tier3_first_time_app_user",
            "metro_power_professional",
        ]
    )
    assert len(decisions) == 3
    assert decisions[0].tier == AgentTier.SUPERVISOR
    assert decisions[1].tier == AgentTier.MICRO
    assert decisions[2].tier == AgentTier.WORKER


def test_route_batch_pairs_profiles_in_order() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
    )

    router = AgentHierarchyRouter()
    # Two unmapped clusters with distinct profiles → each gets per-cluster routing.
    decisions = router.route_batch(
        [
            "unmapped_alpha",
            "unmapped_beta",
        ],
        agent_profiles=[
            {"digital_literacy": 0.9, "patience_score": 0.9},
            {"digital_literacy": 0.1, "patience_score": 0.1},
        ],
    )
    assert decisions[0].tier == AgentTier.WORKER
    assert decisions[1].tier == AgentTier.MICRO


def test_route_batch_with_no_profiles_uses_empty_default() -> None:
    """``agent_profiles=None`` should not raise and should fall to defaults."""
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    decisions = router.route_batch(
        ["unmapped_a", "unmapped_b"],
        agent_profiles=None,
    )
    assert len(decisions) == 2
    # Each will be WORKER (default).
    for d in decisions:
        assert d.tier.value == "WORKER"


def test_tier_summary_counts_each_tier() -> None:
    from app.simulation.agent_hierarchy import (
        AgentHierarchyRouter,
        AgentTier,
        AgentRoutingDecision,
    )

    router = AgentHierarchyRouter()
    decisions = [
        AgentRoutingDecision(cluster_id="a", tier=AgentTier.MICRO, reason="", confidence=1.0),
        AgentRoutingDecision(cluster_id="b", tier=AgentTier.WORKER, reason="", confidence=1.0),
        AgentRoutingDecision(cluster_id="c", tier=AgentTier.WORKER, reason="", confidence=1.0),
        AgentRoutingDecision(cluster_id="d", tier=AgentTier.SUPERVISOR, reason="", confidence=1.0),
    ]
    summary = router.tier_summary(decisions)
    assert summary["MICRO"] == 1
    assert summary["WORKER"] == 2
    assert summary["SUPERVISOR"] == 1
    assert summary["total"] == 4


def test_tier_summary_handles_empty_input() -> None:
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    summary = router.tier_summary([])
    assert summary == {
        "MICRO": 0,
        "WORKER": 0,
        "SUPERVISOR": 0,
        "total": 0,
    }


# ---------------------------------------------------------------------------
# Determinism + dataclass shape
# ---------------------------------------------------------------------------


def test_route_is_deterministic() -> None:
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    a = router.route("metro_power_professional")
    b = router.route("metro_power_professional")
    assert a.tier == b.tier
    assert a.reason == b.reason
    assert a.confidence == b.confidence


def test_routing_decision_dataclass_carries_all_fields() -> None:
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    decision = router.route("senior_enterprise_decision_maker")
    # Validate the dataclass surface.
    assert hasattr(decision, "cluster_id")
    assert hasattr(decision, "tier")
    assert hasattr(decision, "reason")
    assert hasattr(decision, "confidence")
    assert isinstance(decision.confidence, float)
    assert 0.0 <= decision.confidence <= 1.0


def test_unmapped_cluster_reason_includes_default_text() -> None:
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    decision = router.route("totally_unknown_xyz")
    assert "default" in decision.reason.lower() or "no strong" in decision.reason.lower()


# ---------------------------------------------------------------------------
# Validation: unknown hardcoded ids log a warning but do not raise
# ---------------------------------------------------------------------------


def test_unknown_ids_in_hardcoded_maps_do_not_crash_router() -> None:
    """If the registry isn't importable, the router still constructs cleanly."""
    from app.simulation.agent_hierarchy import AgentHierarchyRouter

    router = AgentHierarchyRouter()
    decision = router.route("tier3_first_time_app_user")
    assert decision.tier.value == "MICRO"
