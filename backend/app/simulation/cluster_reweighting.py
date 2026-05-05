"""
ClusterReweightingEngine — deterministic demographic reweighting for targeted simulations.

Uses rule bundles keyed by product scenario (not raw ProductType alone) so static
registry weights better match B2B vs B2C, price tier, and category.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.product_type import ProductType


@dataclass(frozen=True)
class ReweightRules:
    """Suppress clusters to 0 weight; amplify others by multiplier; then normalize."""
    suppress: tuple[str, ...] = ()
    amplify: dict[str, float] = field(default_factory=dict)


# Rule bundles (learning-system plan names)
REWEIGHTING_RULES: dict[str, ReweightRules] = {
    "B2B_ENTERPRISE": ReweightRules(
        suppress=(
            "high_literacy_student_freemium_ceiling",
            "low_literacy_student_passive",
            "tier3_first_time_app_user",
            "tier3_community_influenced_buyer",
            "value_hardware_buyer",
            "gift_hardware_buyer",
            "impulsive_trend_follower",
        ),
        amplify={
            "senior_enterprise_decision_maker": 8.0,
            "mid_market_it_decision_maker": 7.0,
            "technical_founder_evaluator": 5.0,
            "enterprise_procurement_gatekeeper": 4.0,
            "non_technical_co_founder_buyer": 4.0,
        },
    ),
    "CONSUMER_HARDWARE_LOW_PRICE": ReweightRules(
        amplify={
            "value_hardware_buyer": 3.5,
            "tier2_price_sensitive_pragmatist": 2.5,
            "replacement_hardware_buyer": 2.0,
            "impulsive_trend_follower": 1.8,
            "tier3_community_influenced_buyer": 1.4,
        },
    ),
    "CONSUMER_HARDWARE_MID": ReweightRules(
        amplify={
            "urban_mid_income_hardware_considerer": 2.2,
            "considered_hardware_researcher": 2.0,
            "replacement_hardware_buyer": 1.6,
            "tier2_price_sensitive_pragmatist": 1.5,
            "early_hardware_adopter_tech_enthusiast": 1.8,
        },
    ),
    "CONSUMER_HARDWARE_PREMIUM": ReweightRules(
        amplify={
            "high_income_hardware_enthusiast": 3.0,
            "affluent_metro_late_majority": 2.0,
            "considered_hardware_researcher": 1.8,
            "wealthy_health_conscious_buyer": 1.5,
        },
    ),
    "HEALTH_HARDWARE": ReweightRules(
        suppress=(
            "high_literacy_student_freemium_ceiling",
            "low_literacy_student_passive",
            "college_group_purchase",
            "impulsive_trend_follower",
        ),
        amplify={
            "health_hardware_skeptic": 4.0,
            "health_hardware_enthusiast": 3.5,
            "wealthy_health_conscious_buyer": 3.0,
            "anxiety_driven_researcher": 2.0,
        },
    ),
    "IOT_HARDWARE": ReweightRules(
        amplify={
            "smart_home_early_adopter": 4.0,
            "high_income_early_adopter": 2.5,
            "high_income_hardware_enthusiast": 2.0,
            "tier2_educated_young_parent": 1.5,
        },
    ),
    "WEARABLE": ReweightRules(
        amplify={
            "high_income_hardware_enthusiast": 2.8,
            "health_hardware_enthusiast": 2.2,
            "young_urban_professional_first_job": 2.0,
            "impulsive_trend_follower": 1.6,
            "urban_mid_income_hardware_considerer": 1.5,
        },
    ),
    "SAAS_B2C": ReweightRules(
        amplify={
            "urban_mid_income_saas_buyer": 1.5,
            "mid_income_startup_founder": 1.8,
            "young_urban_professional_first_job": 1.3,
            "high_literacy_student_freemium_ceiling": 1.2,
        },
    ),
    "SAAS_B2B_SMB": ReweightRules(
        amplify={
            "smb_owner_self_serve": 2.5,
            "smb_owner_referral_dependent": 2.0,
            "mid_market_it_decision_maker": 2.2,
            "technical_founder_evaluator": 1.8,
            "tier2_aspirational_founder": 1.6,
        },
    ),
    "SAAS_ENTERPRISE": ReweightRules(
        suppress=(
            "high_literacy_student_freemium_ceiling",
            "low_literacy_student_passive",
            "college_group_purchase",
        ),
        amplify={
            "senior_enterprise_decision_maker": 6.0,
            "enterprise_procurement_gatekeeper": 5.0,
            "mid_market_it_decision_maker": 4.0,
            "non_technical_co_founder_buyer": 3.0,
        },
    ),
    "DEFAULT": ReweightRules(),
}


class ClusterReweightingEngine:
    """Apply scenario-specific suppress/amplify rules and renormalize to sum 1.0."""

    def compute_weights(
        self,
        product_type: ProductType,
        aov: float,
        geography: str,
        segment: str,
        age_target: str,
    ) -> dict[str, float]:
        registry = ClusterRegistry()
        base = {c.cluster_id: c.population_weight for c in registry.all_clusters()}

        rule_key = self._select_rule_bundle(product_type, aov, geography, segment, age_target)
        rules = REWEIGHTING_RULES.get(rule_key, REWEIGHTING_RULES["DEFAULT"])

        for cid in rules.suppress:
            if cid in base:
                base[cid] = 0.0
        for cid, mult in rules.amplify.items():
            if cid in base:
                base[cid] *= mult

        self._apply_geo_age_tweaks(base, geography, age_target)

        total = sum(base.values())
        if total == 0:
            total = 1.0
        return {k: v / total for k, v in base.items()}

    def _select_rule_bundle(
        self,
        product_type: ProductType,
        aov: float,
        geography: str,
        segment: str,
        age_target: str,
    ) -> str:
        seg = segment.strip().upper()
        geo = geography.strip().upper()

        if product_type == ProductType.ENTERPRISE_SOFTWARE:
            return "B2B_ENTERPRISE"
        if product_type == ProductType.B2B_HARDWARE:
            return "B2B_ENTERPRISE"

        if product_type == ProductType.HEALTH_HARDWARE:
            return "HEALTH_HARDWARE"
        if product_type == ProductType.IOT_HARDWARE:
            return "IOT_HARDWARE"
        if product_type == ProductType.WEARABLE:
            return "WEARABLE"

        if product_type == ProductType.CONSUMER_HARDWARE:
            if aov < 3000:
                return "CONSUMER_HARDWARE_LOW_PRICE"
            if aov < 12000:
                return "CONSUMER_HARDWARE_MID"
            return "CONSUMER_HARDWARE_PREMIUM"

        # SaaS-like categories: segment drives bundle
        if product_type in (
            ProductType.SAAS,
            ProductType.MARKETPLACE,
            ProductType.MOBILE_APP,
            ProductType.DEVELOPER_TOOL,
        ):
            if seg in ("ENTERPRISE", "B2B_ENTERPRISE", "FORTUNE"):
                return "SAAS_ENTERPRISE"
            if seg in ("SMB", "B2B_SMB", "SMB_B2B"):
                return "SAAS_B2B_SMB"
            return "SAAS_B2C"

        return "DEFAULT"

    def _apply_geo_age_tweaks(
        self,
        base: dict[str, float],
        geography: str,
        age_target: str,
    ) -> None:
        """Light deterministic nudges — no historical data required."""
        g = geography.upper()
        a = age_target.upper()

        if "TIER3" in g or g in ("RURAL", "TIER_3"):
            for cid in list(base.keys()):
                if "tier3" in cid:
                    base[cid] *= 1.35
        if "TIER2" in g and "TIER3" not in g:
            for cid in list(base.keys()):
                if "tier2" in cid:
                    base[cid] *= 1.15

        if any(x in a for x in ("18", "YOUTH", "STUDENT", "17-22", "UNDER_25")):
            for cid in list(base.keys()):
                if any(k in cid for k in ("student", "college", "graduate")):
                    base[cid] *= 1.25
        if any(x in a for x in ("45", "50", "55", "SENIOR", "60")):
            for cid in list(base.keys()):
                if any(k in cid for k in ("senior", "late_majority", "affluent_metro_late")):
                    base[cid] *= 1.2
