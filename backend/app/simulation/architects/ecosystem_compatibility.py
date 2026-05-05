"""
EcosystemCompatibilityArchitect — platform lock-in, smart home, subscriptions, and cloud tolerance.

Feeds downstream — no transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class EcosystemCompatibilityArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "EcosystemCompatibilityArchitect"

    @property
    def product_types(self) -> list[str]:
        return ["consumer_hardware", "health_hardware", "iot_hardware", "wearable"]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t            = cluster.base_traits
        income       = t["income_level"]
        trust        = t["trust"]
        literacy     = t["digital_literacy"]
        price_s      = t["price_sensitivity"]
        social       = t["social_orientation"]
        risk_av      = t["risk_aversion"]
        age          = cluster.demographic_profile.get("age_bracket", "25-35")
        family_ori   = (
            0.7 if any(x in cluster.cluster_id for x in ["couple", "family", "parent"]) else
            0.3
        )
        product_type = str(env_params.get("product_type", "consumer_hardware"))

        # ── Extract signals from assumptions ──────────────────────────────
        matter_support    = False
        has_subscription  = False
        has_api           = False
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["matter", "alexa", "google home", "apple home"]):
                matter_support = True
            if any(w in text for w in ["subscription", "monthly fee", "annual plan", "recurring"]):
                has_subscription = True
            if any(w in text for w in ["api", "developer", "sdk", "webhook"]):
                has_api = True

        # ── Metrics ───────────────────────────────────────────────────────
        platform_lock = min(0.85,
            (1 - risk_av) * 0.5 * (1.2 if literacy > 0.6 else 0.8)
        )

        smart_home_req = (
            min(0.80, income * 0.4 + literacy * 0.35)
            if product_type == "iot_hardware" else
            min(0.40, income * 0.2)
        )
        smart_home_req *= (1.3 if matter_support else 0.6)

        cross_device = min(0.80,
            literacy * 0.4 * (1.5 if "enthusiast" in cluster.cluster_id else 0.8)
        )

        accessory_attach = min(0.80,
            income * 0.4
            + (0.3 if "enthusiast" in cluster.cluster_id else 0.0)
            + (0.2 if literacy > 0.7 else 0.0)
        )

        subscription_resentment = (
            min(0.85,
                price_s * 0.5 * (
                    1.6 if income < 0.3 else
                    0.6 if income > 0.7 else
                    1.0
                )
            ) if has_subscription else 0.10
        )

        api_interest = (
            min(0.80, literacy * 0.5 * (1.8 if product_type == "iot_hardware" else 0.7))
            if has_api else 0.05
        )

        household_sharing = min(0.80,
            family_ori * 0.5 * (
                1.6 if product_type in ["iot_hardware", "consumer_hardware"] else 0.4
            )
        )

        cloud_tolerance = min(0.85,
            trust * 0.5 * (0.7 if product_type == "health_hardware" else 1.0)
        )

        voice_expect = (
            min(0.70, income * 0.3 + literacy * 0.2)
            if any(x in age for x in ["25", "28", "30", "32", "35"]) else
            min(0.40, income * 0.2)
        )

        compatibility_gate = smart_home_req if product_type == "iot_hardware" else platform_lock
        severity = "WARNING" if subscription_resentment > 0.60 else "INFO"

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "platform_lockin_acceptance":           round(platform_lock, 4),
                "smart_home_compatibility_requirement": round(smart_home_req, 4),
                "cross_device_interoperability":        round(cross_device, 4),
                "accessory_attach_rate":                round(accessory_attach, 4),
                "subscription_hardware_resentment":     round(subscription_resentment, 4),
                "developer_api_interest":               round(api_interest, 4),
                "household_sharing_behaviour":          round(household_sharing, 4),
                "cloud_storage_tolerance":              round(cloud_tolerance, 4),
                "voice_assistant_expectation":          round(voice_expect, 4),
                "ecosystem_compatibility_gate":         round(compatibility_gate, 4),
            },
            flags={
                "subscription_resentment_high":  subscription_resentment > 0.60,
                "ecosystem_incompatibility_risk": compatibility_gate > 0.65 and not matter_support,
                "cloud_privacy_concern":          cloud_tolerance < 0.35,
            },
            narrative_findings=[
                f"Accessory attach: {accessory_attach * 100:.1f}% | Subscription resentment: {subscription_resentment * 100:.1f}%",
                f"Cloud tolerance: {cloud_tolerance:.2f} | Smart home req: {smart_home_req:.2f}",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        resentment = [o for o in outputs if o.flags.get("subscription_resentment_high")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(resentment)} clusters resent hardware subscription model",
            affected_cluster_ids=[o.cluster_id for o in resentment],
            population_fraction=round(len(resentment) * 0.05, 3),
            conversion_impact=round(len(resentment) * 0.03, 3),
            recommended_action="Make subscription optional or include in hardware price",
            severity="WARNING" if resentment else "INFO",
        )
