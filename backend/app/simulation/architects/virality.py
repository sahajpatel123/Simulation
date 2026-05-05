"""
ViralityArchitect — models referral, word-of-mouth, and viral-K behaviour.

No transition_overrides — outputs feed the growth model, not the funnel directly.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class ViralityArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "ViralityArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "saas", "marketplace", "mobile_app",
            "consumer_hardware", "health_hardware",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        motivation = t["motivation"]
        trust      = t["trust"]
        income     = t["income_level"]
        social     = t["social_orientation"]

        # ── Satisfaction proxy from upstream retention outputs ─────────────
        day30 = agent_profile.get("day30_survival", 0.20)
        depth = agent_profile.get("feature_depth_score", 0.40)
        satisfaction_proxy = day30 * 0.5 + depth * 0.3 + trust * 0.2

        # ── Core metrics ───────────────────────────────────────────────────
        identity_mult = (
            1.4 if "professional" in cluster.cluster_id else
            1.6 if "early_adopter" in cluster.cluster_id else
            1.0
        )
        organic_trigger = min(0.30, satisfaction_proxy * social * identity_mult)

        incentive_quality = min(0.90, income * 0.5 + trust * 0.4)
        if income < 0.2:
            incentive_quality *= 0.5   # low-income referrers attract reward-seekers

        wom_mult = (
            1.5 if "professional" in cluster.cluster_id else
            1.3 if "founder" in cluster.cluster_id else
            0.8
        )
        wom_coeff = min(2.0, social * 0.6 * wom_mult)

        product_type  = str(env_params.get("product_type", "saas"))
        net_threshold = {"marketplace": 200, "saas": 100, "mobile_app": 500}.get(
            product_type, 100
        )

        invite_rate  = min(0.80, social * 0.5 + motivation * 0.3 * trust)
        shareable    = bool(agent_profile.get("shareable_output", False))
        content_vir  = min(0.40, social * 0.4 * (1.6 if shareable else 0.3))

        referred_conv = min(0.80, trust * 1.4)
        viral_k       = min(2.0, organic_trigger * invite_rate * referred_conv)

        community_mult = (
            1.5 if any(x in cluster.cluster_id
                       for x in ["founder", "professional", "enthusiast"])
            else 0.7
        )
        community = min(0.60, social * 0.35 * trust * community_mult)

        severity = "INFO" if viral_k > 0.10 else "WARNING"

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "organic_referral_trigger_score":      round(organic_trigger, 4),
                "referral_incentive_response_quality": round(incentive_quality, 4),
                "word_of_mouth_coefficient":           round(wom_coeff, 4),
                "network_effect_threshold":            float(net_threshold),
                "invite_completion_rate":              round(invite_rate, 4),
                "content_virality_rate":               round(content_vir, 4),
                "viral_coefficient":                   round(viral_k, 4),
                "community_building_participation":    round(community, 4),
            },
            flags={
                "viral_growth_possible":  viral_k > 1.0,
                "strong_wom_channel":     wom_coeff > 1.2,
                "incentive_quality_risk": incentive_quality < 0.40,
            },
            narrative_findings=[
                f"Viral coefficient (K): {viral_k:.3f}",
                f"Organic referral trigger: {organic_trigger * 100:.1f}%",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        viral = [o for o in outputs if o.flags.get("viral_growth_possible")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(viral)} clusters can drive viral growth (K>1)",
            affected_cluster_ids=[o.cluster_id for o in viral],
            population_fraction=round(len(viral) * 0.05, 3),
            conversion_impact=round(len(viral) * 0.05, 3),
            recommended_action="Build referral flow, create shareable outputs",
            severity="INFO",
        )
