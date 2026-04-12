"""
PurchaseDecisionArchitect — hardware purchase willingness, EMI, and payment structure.

Includes transition overrides for BROWSE→CONSIDER, CONSIDER→DECIDE, DECIDE→PURCHASE.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class PurchaseDecisionArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "PurchaseDecisionArchitect"

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
        t          = cluster.base_traits
        income     = t["income_level"]
        price_s    = t["price_sensitivity"]
        risk_av    = t["risk_aversion"]
        literacy   = t["digital_literacy"]
        patience   = t["patience_score"]
        motivation = t["motivation"]
        trust      = t["trust"]
        age        = cluster.demographic_profile.get("age_bracket", "25-35")
        geo        = cluster.demographic_profile.get("geography", "metro")
        AOV        = float(env_params.get("average_order_value", 3000))
        product_type = str(env_params.get("product_type", "consumer_hardware"))

        brand_mult = float(agent_profile.get("brand_deficit_multiplier", 0.8))
        urgency    = float(agent_profile.get("problem_urgency_intensity", 0.5))

        # ── Extract assumptions ───────────────────────────────────────────
        has_emi    = False
        has_bnpl   = False
        return_days = 7
        warranty_y  = 1
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["emi", "installment", "no cost emi"]):
                has_emi = True
            if any(w in text for w in ["bnpl", "buy now pay later", "simpl", "lazypay"]):
                has_bnpl = True
            if "30 day" in text or "30-day return" in text:
                return_days = 30
            elif "15 day" in text:
                return_days = 15
            if "2 year" in text or "2-year warranty" in text:
                warranty_y = 2
            elif "3 year" in text:
                warranty_y = 3

        # ── Upfront cost ceiling ──────────────────────────────────────────
        geo_mult = {"metro": 1.0, "tier2": 0.75, "tier3": 0.55}.get(geo, 1.0)
        ceiling  = income * 25000 * (1 - price_s * 0.6) * brand_mult * geo_mult
        ceiling  = max(200.0, min(50000.0, ceiling))
        if urgency > 0.8:
            ceiling *= 1.25

        # ── EMI ───────────────────────────────────────────────────────────
        emi_likelihood = 0.0
        if has_emi:
            emi_likelihood = (1 - income) * 0.7 * (1.5 if AOV > ceiling * 0.8 else 1.0)
            emi_likelihood *= (0.5 if brand_mult < 0.6 else 1.0)
            emi_likelihood *= (0.7 if literacy < 0.4 else 1.0)
            emi_likelihood = min(0.85, emi_likelihood)

        if   income > 0.60:  emi_tenure = 3
        elif income > 0.35:  emi_tenure = 6
        elif income > 0.20:  emi_tenure = 9
        else:                emi_tenure = 12
        if AOV > 10000:
            emi_tenure = min(12, emi_tenure + 3)

        bnpl = 0.0
        if has_bnpl:
            age_mult = 1.5 if any(x in age for x in ["18", "22", "25"]) else 0.4
            bnpl = min(0.60, literacy * 0.4 * age_mult)

        impulse_thresh = AOV * (1 - price_s) * 0.3 * (
            1.8 if "impulsive" in cluster.cluster_id else
            0.2 if "minimalist" in cluster.cluster_id else
            1.0
        )

        consider_days = max(1, int(
            risk_av * 21
            * (1.5 if AOV > 15000 else 0.5 if AOV < 2000 else 1.0)
            * (0.4 if urgency > 0.8 else 1.0)
        ))

        gift_prob = 0.0
        if any(x in cluster.cluster_id for x in ["gift", "family", "parent", "couple"]):
            gift_prob = 0.65
        elif product_type in ["wearable", "health_hardware"]:
            gift_prob = 0.30

        b2b_trigger = 5 if any(x in cluster.cluster_id for x in ["enterprise", "b2b", "smb"]) else 0

        adoption_score = float(agent_profile.get("technology_adoption_score", 0.6))
        upgrade_months = max(12, int(
            (18 + risk_av * 18)
            * (0.6 if adoption_score > 0.7 else 1.5 if income < 0.3 else 1.0)
        ))

        trade_in = min(0.50, income * 0.3 + (0.2 if geo == "metro" else 0.0))

        compare_sources = max(1, int(literacy * 5 + risk_av * 3 + (2 if AOV > 10000 else 0)))
        compare_sources = int(min(10, compare_sources * (
            2.0 if "researcher" in cluster.cluster_id else
            0.3 if "impulsive"  in cluster.cluster_id else
            1.0
        )))

        return_effect = (
            risk_av * 0.35
            * (1.6 if brand_mult < 0.65 else 1.0)
            * (1.45 if return_days >= 30 else 1.0 if return_days >= 14 else 0.8)
        )

        will_pay_upfront = min(0.95, ceiling / AOV) if AOV > 0 else 0.5
        will_pay_any     = max(0.05, min(0.95, will_pay_upfront + emi_likelihood * 0.4))

        severity = (
            "CRITICAL" if ceiling < AOV * 0.4 and not has_emi else
            "WARNING"  if ceiling < AOV * 0.7 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "upfront_cost_ceiling":           round(ceiling, 2),
                "emi_adoption_likelihood":        round(emi_likelihood, 4),
                "emi_preferred_tenure_months":    float(emi_tenure),
                "bnpl_likelihood":                round(bnpl, 4),
                "impulse_threshold_inr":          round(impulse_thresh, 2),
                "considered_purchase_days":       float(consider_days),
                "gift_purchase_probability":      round(gift_prob, 4),
                "b2b_bulk_trigger_units":         float(b2b_trigger),
                "upgrade_cycle_months":           float(upgrade_months),
                "trade_in_participation":         round(trade_in, 4),
                "price_comparison_sources":       float(compare_sources),
                "return_policy_conversion_effect": round(return_effect, 4),
                "will_pay_probability":           round(will_pay_any, 4),
            },
            flags={
                "price_kill_shot": ceiling < AOV * 0.4 and not has_emi,
                "emi_critical":    emi_likelihood > 0.55,
                "gift_segment":    gift_prob > 0.40,
                "b2b_segment":     b2b_trigger > 0,
            },
            narrative_findings=[
                f"Ceiling ₹{ceiling:.0f} vs AOV ₹{AOV:.0f} | EMI: {emi_likelihood * 100:.1f}%",
                f"Consider timeline: {consider_days} days",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        will_pay = output.metrics.get("will_pay_probability", 0.5)
        emi      = output.metrics.get("emi_adoption_likelihood", 0.0)
        ret_eff  = output.metrics.get("return_policy_conversion_effect", 0.2)
        return {
            ("BROWSE",   "CONSIDER"): max(0.05, min(0.95, will_pay + emi * 0.2)),
            ("CONSIDER", "DECIDE"):   max(0.05, min(0.95, will_pay * (1 + ret_eff * 0.3))),
            ("DECIDE",   "PURCHASE"): max(0.05, min(0.95, will_pay)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        kill = [o for o in outputs if o.flags.get("price_kill_shot")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(kill)} clusters cannot afford AOV without EMI",
            affected_cluster_ids=[o.cluster_id for o in kill],
            population_fraction=round(len(kill) * 0.06, 3),
            conversion_impact=round(len(kill) * 0.05, 3),
            recommended_action="Add EMI option or lower price for affected segments",
            severity="CRITICAL" if kill else "INFO",
        )
