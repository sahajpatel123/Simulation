"""
DemographicInteractionArchitect — compound demographic / geo / household corrections.

Runs LAST in the Conductor stack as a correction layer. No transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


def _is_tier3_geo(geo: str) -> bool:
    """Match registry values like tier3_rural as well as plain tier3."""
    g = geo.lower()
    return g == "tier3" or g == "tier3_rural" or g.startswith("tier3_")


def _is_tier2_geo(geo: str) -> bool:
    g = geo.lower()
    if _is_tier3_geo(geo):
        return False
    return g == "tier2" or g.startswith("tier2_")


class DemographicInteractionArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "DemographicInteractionArchitect"

    @property
    def product_types(self) -> list[str]:
        return self.ALL_PRODUCT_TYPES

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t           = cluster.base_traits
        income      = t["income_level"]
        motivation  = t["motivation"]
        price_s     = t["price_sensitivity"]
        literacy    = t["digital_literacy"]
        trust       = t["trust"]
        social      = t["social_orientation"]
        family_ori  = (
            0.7 if any(x in cluster.cluster_id for x in ["couple", "family", "parent", "joint"]) else
            0.3
        )
        age = cluster.demographic_profile.get("age_bracket", "25-35")
        geo = cluster.demographic_profile.get("geography", "metro")
        tier3 = _is_tier3_geo(geo)
        tier2 = _is_tier2_geo(geo)

        # ── Regional language from assumptions ────────────────────────────
        has_regional_lang = False
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["hindi", "regional language", "vernacular", "multilingual"]):
                has_regional_lang = True

        corrections: dict[str, float] = {}

        # 1. Motivation overrides price sensitivity
        if motivation > 0.80 and price_s > 0.70:
            corrections["price_ceiling_interaction_mult"] = round(1.0 + motivation * 0.32, 4)
        else:
            corrections["price_ceiling_interaction_mult"] = 1.0

        # 2. Metro vs Tier-3 compound literacy gap
        if tier3 and literacy < 0.50:
            corrections["onboarding_compound_correction"] = 0.55
            corrections["support_ticket_compound_mult"]   = 1.45
            corrections["social_proof_threshold_mult"]    = 1.30
        elif tier2 and literacy < 0.55:
            corrections["onboarding_compound_correction"] = 0.82
            corrections["support_ticket_compound_mult"]   = 1.20
            corrections["social_proof_threshold_mult"]    = 1.10
        else:
            corrections["onboarding_compound_correction"] = 1.0
            corrections["support_ticket_compound_mult"]   = 1.0
            corrections["social_proof_threshold_mult"]    = 1.0

        # 3. Age × trust social proof interaction
        if any(x in age for x in ["45", "50", "55"]):
            corrections["social_proof_age_mult"]   = 1.42
            corrections["trust_decay_age_mult"]    = 1.35
            corrections["trust_recovery_age_mult"] = 1.60
        elif any(x in age for x in ["18", "22", "24"]):
            corrections["social_proof_age_mult"]   = 0.65
            corrections["trust_decay_age_mult"]    = 0.80
            corrections["trust_recovery_age_mult"] = 0.65
        else:
            corrections["social_proof_age_mult"]   = 1.0
            corrections["trust_decay_age_mult"]    = 1.0
            corrections["trust_recovery_age_mult"] = 1.0

        # 4. Regional language effect
        if tier3 and not has_regional_lang:
            corrections["regional_onboarding_penalty"] = 0.65
        elif tier2 and not has_regional_lang:
            corrections["regional_onboarding_penalty"] = 0.83
        else:
            corrections["regional_onboarding_penalty"] = 1.0

        # 5. Joint family / household dynamics
        if family_ori > 0.60:
            corrections["household_income_mult"] = 1.65
            corrections["decision_cycle_mult"]   = 1.45
            corrections["gift_probability_mult"] = 1.55
            corrections["packaging_weight_mult"] = 1.35
        else:
            corrections["household_income_mult"] = 1.0
            corrections["decision_cycle_mult"]   = 1.0
            corrections["gift_probability_mult"] = 1.0
            corrections["packaging_weight_mult"] = 1.0

        # 6. Student compound constraint
        if any(x in cluster.cluster_id for x in ["student", "college", "graduate"]):
            corrections["freemium_ceiling_student_mult"] = 0.48
            corrections["viral_coefficient_student_mult"] = 1.65
            corrections["community_participation_mult"]  = 1.45
        else:
            corrections["freemium_ceiling_student_mult"] = 1.0
            corrections["viral_coefficient_student_mult"] = 1.0
            corrections["community_participation_mult"]  = 1.0

        overall = (
            corrections["price_ceiling_interaction_mult"]
            * corrections["onboarding_compound_correction"]
            * corrections.get("regional_onboarding_penalty", 1.0)
        )
        corrections["overall_demographic_correction"] = round(max(0.10, min(2.0, overall)), 4)

        active_corrections = [
            k for k, v in corrections.items()
            if v != 1.0 and k != "overall_demographic_correction"
        ]
        severity = "WARNING" if len(active_corrections) >= 3 else "INFO"

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics=corrections,
            flags={
                "motivation_overrides_price": corrections["price_ceiling_interaction_mult"] > 1.0,
                "tier3_compound_gap":         corrections["onboarding_compound_correction"] < 0.70,
                "regional_language_gap":      corrections.get("regional_onboarding_penalty", 1.0) < 1.0,
                "joint_family_dynamics":      corrections["household_income_mult"] > 1.0,
                "student_compound":           corrections["freemium_ceiling_student_mult"] < 1.0,
            },
            narrative_findings=[
                f"Active corrections: {active_corrections}",
                f"Overall demographic correction: {corrections['overall_demographic_correction']:.2f}x",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        tier3_gap = [o for o in outputs if o.flags.get("tier3_compound_gap")]
        lang_gap  = [o for o in outputs if o.flags.get("regional_language_gap")]
        affected  = list({o.cluster_id for o in tier3_gap + lang_gap})
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(tier3_gap)} Tier-3 clusters have compound literacy gap; "
                f"{len(lang_gap)} have regional language gap"
            ),
            affected_cluster_ids=affected,
            population_fraction=round((len(tier3_gap) + len(lang_gap)) * 0.04, 3),
            conversion_impact=round(len(tier3_gap) * 0.05, 3),
            recommended_action="Add Hindi UI, simplify onboarding for Tier-3 clusters",
            severity="WARNING" if (tier3_gap or lang_gap) else "INFO",
        )
