from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentTier(str, Enum):
    MICRO = "MICRO"  # stochastic outcome, no browser
    WORKER = "WORKER"  # full Playwright session
    SUPERVISOR = "SUPERVISOR"  # multi-step deliberation, ambiguity handling


@dataclass
class AgentRoutingDecision:
    cluster_id: str
    tier: AgentTier
    reason: str
    confidence: float


# ── Cluster ID → Tier rules ──
# Based on real behavioral logic, not arbitrary mapping.
# MICRO = bounces fast in reality, full browser would fake depth.
# SUPERVISOR = deliberates, has ambiguous decision states, needs reasoning.
# WORKER = default full browser engagement.

SUPERVISOR_CLUSTERS = {
    "senior_enterprise_decision_maker",
    "enterprise_procurement_gatekeeper",
    "mid_market_it_decision_maker",
    "technical_founder_evaluator",
    "non_technical_co_founder_buyer",
    "health_hardware_skeptic",
    "health_hardware_enthusiast",
    "wealthy_health_conscious_buyer",
    "anxiety_driven_researcher",
    "considered_hardware_researcher",
}

MICRO_CLUSTERS = {
    "low_literacy_student_passive",
    "tier3_first_time_app_user",
    "tier3_community_influenced_buyer",
    "impulsive_trend_follower",
    "college_group_purchase",
    "peer_pressure_converter",
    "retiree_digital_explorer",
}


_VALIDATED_HIERARCHY_IDS: set[str] | None = None


def _validate_hierarchy_ids() -> None:
    """Warn if any hardcoded cluster ID in hierarchy maps is unknown."""
    global _VALIDATED_HIERARCHY_IDS
    if _VALIDATED_HIERARCHY_IDS is not None:
        return
    try:
        from app.simulation.clusters.registry import ClusterRegistry

        known = {c.cluster_id for c in ClusterRegistry().all_clusters()}
    except Exception:
        known = set()
    all_ids = SUPERVISOR_CLUSTERS | MICRO_CLUSTERS
    unknown = all_ids - known
    for uid in sorted(unknown):
        logger.warning(
            "[AgentHierarchy] Unknown cluster ID '%s' in hierarchy rules — "
            "may be renamed in registry but not updated here.",
            uid,
        )
    _VALIDATED_HIERARCHY_IDS = all_ids


class AgentHierarchyRouter:

    def __init__(self) -> None:
        _validate_hierarchy_ids()

    def route(
        self,
        cluster_id: str,
        agent_profile: dict[str, Any] | None = None,
        architect_outputs: dict[str, Any] | None = None,
    ) -> AgentRoutingDecision:
        """
        Route cluster to correct agent tier.
        Priority: explicit map → literacy trait → default WORKER.
        """
        if cluster_id in SUPERVISOR_CLUSTERS:
            return AgentRoutingDecision(
                cluster_id=cluster_id,
                tier=AgentTier.SUPERVISOR,
                reason="Enterprise/health/complex deliberation cluster",
                confidence=0.95,
            )

        if cluster_id in MICRO_CLUSTERS:
            return AgentRoutingDecision(
                cluster_id=cluster_id,
                tier=AgentTier.MICRO,
                reason="Low-literacy/quick-bounce cluster — micro is MORE accurate",
                confidence=0.92,
            )

        # Trait-based fallback if agent_profile available
        if agent_profile:
            literacy = float(agent_profile.get("digital_literacy", 0.5))
            patience = float(agent_profile.get("patience_score", 0.5))

            if literacy < 0.30 or patience < 0.25:
                return AgentRoutingDecision(
                    cluster_id=cluster_id,
                    tier=AgentTier.MICRO,
                    reason=f"Low literacy({literacy:.2f}) or patience({patience:.2f})",
                    confidence=0.80,
                )
            if literacy > 0.75 and patience > 0.60:
                return AgentRoutingDecision(
                    cluster_id=cluster_id,
                    tier=AgentTier.WORKER,
                    reason=f"High literacy({literacy:.2f}) and patience({patience:.2f})",
                    confidence=0.85,
                )

        # Keyword fallback on cluster_id string
        cid = cluster_id.lower()
        if any(k in cid for k in ["b2b", "enterprise", "health", "smb_owner"]):
            return AgentRoutingDecision(
                cluster_id=cluster_id,
                tier=AgentTier.SUPERVISOR,
                reason="Cluster name signals complex decision domain",
                confidence=0.75,
            )
        if any(k in cid for k in ["tier3", "passive", "low_literacy", "impulsive"]):
            return AgentRoutingDecision(
                cluster_id=cluster_id,
                tier=AgentTier.MICRO,
                reason="Cluster name signals quick-bounce behavior",
                confidence=0.75,
            )

        return AgentRoutingDecision(
            cluster_id=cluster_id,
            tier=AgentTier.WORKER,
            reason="No strong signal — default full browser session",
            confidence=0.60,
        )

    def needs_browser(self, decision: AgentRoutingDecision) -> bool:
        return decision.tier in (AgentTier.WORKER, AgentTier.SUPERVISOR)

    def is_micro(self, decision: AgentRoutingDecision) -> bool:
        return decision.tier == AgentTier.MICRO

    def route_batch(
        self,
        cluster_ids: list[str],
        agent_profiles: list[dict] | None = None,
        architect_outputs: dict[str, Any] | None = None,
    ) -> list[AgentRoutingDecision]:
        profiles = agent_profiles or [{}] * len(cluster_ids)
        return [
            self.route(cid, prof, architect_outputs)
            for cid, prof in zip(cluster_ids, profiles)
        ]

    def tier_summary(self, decisions: list[AgentRoutingDecision]) -> dict:
        from collections import Counter

        counts = Counter(d.tier for d in decisions)
        return {
            "MICRO": counts[AgentTier.MICRO],
            "WORKER": counts[AgentTier.WORKER],
            "SUPERVISOR": counts[AgentTier.SUPERVISOR],
            "total": len(decisions),
        }
