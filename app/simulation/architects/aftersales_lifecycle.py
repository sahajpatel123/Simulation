"""
AftersalesLifecycleArchitect — warranty, repair, support load, loyalty, and review behavior.

Feeds downstream — no transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class AftersalesLifecycleArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "AftersalesLifecycleArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "consumer_hardware", "health_hardware",
            "iot_hardware", "wearable", "b2b_hardware",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t            = cluster.base_traits
        income       = t["income_level"]
        social       = t["social_orientation"]
        patience     = t["patience_score"]
        trust        = t["trust"]
        literacy     = t["digital_literacy"]
        age          = cluster.demographic_profile.get("age_bracket", "25-35")
        AOV          = float(env_params.get("average_order_value", 3000))
        product_type = str(env_params.get("product_type", "consumer_hardware"))

        oob_completion = float(agent_profile.get("oob_setup_completion_rate", 0.80))
        brand_mult     = float(agent_profile.get("brand_deficit_multiplier", 0.8))

        # ── Metrics ───────────────────────────────────────────────────────
        warranty_claim = min(0.40,
            (1 - trust) * 0.25 * (
                1.3 if AOV > 10000 else
                0.7 if AOV < 2000 else
                1.0
            )
        )

        repair_thresh = (
            0.30 if income < 0.3 else
            0.70 if income > 0.7 else
            0.50
        )

        support_30d = min(0.70,
            (1 - literacy) * 0.4 + (1 - oob_completion) * 0.4
        )

        accessory_att = min(0.80,
            income * 0.4 + (0.3 if "enthusiast" in cluster.cluster_id else 0.0)
        )

        refurbished = min(0.50,
            (1 - income) * 0.3
            + (0.2 if any(x in age for x in ["18", "22", "25"]) else 0.0)
        )

        sustainability = min(0.70,
            (0.3 if any(x in age for x in ["18", "22", "25", "28"]) else 0.1)
            + (0.2 if income > 0.5 else 0.0)
        )

        satisfaction_proxy = oob_completion * 0.5 + brand_mult * 0.3 + trust * 0.2
        brand_loyalty_next = min(0.80,
            satisfaction_proxy * (1.4 if accessory_att > 0.3 else 0.8)
        )

        review_likely = min(0.75,
            social * 0.3 * (
                2.5 if satisfaction_proxy < 0.3 or satisfaction_proxy > 0.8 else 0.6
            )
        )

        spare_concern = min(0.60,
            (1 - income) * 0.3 * (1.5 if AOV > 5000 else 0.7)
        )

        lifespan_expect = max(1.0, 1.5 + (AOV / 5000 * 1.5) + (income * 1.0))

        severity = "WARNING" if brand_loyalty_next < 0.30 else "INFO"

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "warranty_claim_likelihood":   round(warranty_claim, 4),
                "repair_vs_replace_threshold": round(repair_thresh, 4),
                "support_contact_rate_30d":    round(support_30d, 4),
                "accessory_attach_rate":       round(accessory_att, 4),
                "refurbished_participation":   round(refurbished, 4),
                "sustainability_concern":      round(sustainability, 4),
                "brand_loyalty_next_purchase": round(brand_loyalty_next, 4),
                "review_writing_likelihood":   round(review_likely, 4),
                "spare_parts_concern":         round(spare_concern, 4),
                "expected_product_lifespan_y": round(lifespan_expect, 2),
            },
            flags={
                "low_brand_loyalty":   brand_loyalty_next < 0.30,
                "high_support_burden": support_30d > 0.40,
                "review_risk_high":    review_likely > 0.50,
            },
            narrative_findings=[
                f"Brand loyalty next purchase: {brand_loyalty_next * 100:.1f}%",
                f"Review probability: {review_likely * 100:.1f}% | Support contact: {support_30d * 100:.1f}%",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        low_loyalty = [o for o in outputs if o.flags.get("low_brand_loyalty")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(low_loyalty)} clusters show low brand loyalty for repeat purchase",
            affected_cluster_ids=[o.cluster_id for o in low_loyalty],
            population_fraction=round(len(low_loyalty) * 0.05, 3),
            conversion_impact=round(len(low_loyalty) * 0.03, 3),
            recommended_action="Improve post-purchase experience, setup flow, and support quality",
            severity="WARNING" if low_loyalty else "INFO",
        )
