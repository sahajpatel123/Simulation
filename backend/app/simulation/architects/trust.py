"""
TrustArchitect — evaluates brand trust barriers and social-proof requirements.

Runs first in the Conductor stack (before Pricing) because brand deficit
multiplies across all downstream conversion steps.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class TrustArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "TrustArchitect"

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
        t = cluster.base_traits
        trust    = t["trust"]
        risk_av  = t["risk_aversion"]
        income   = t["income_level"]
        literacy = t["digital_literacy"]
        social   = t["social_orientation"]
        patience = t["patience_score"]
        skepticism = 1.0 - trust
        age = cluster.demographic_profile.get("age_bracket", "25-35")

        # ── Brand recognition and review count from assumptions ───────────
        brand_recognition = 0.0
        reviews_current   = 0
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["known brand", "established", "recognized"]):
                brand_recognition = 0.7
            if any(w in text for w in ["reviews", "testimonials", "case studies"]):
                reviews_current = 25

        # ── Social proof threshold ────────────────────────────────────────
        age_mult = (
            1.4 if any(x in age for x in ["45", "50", "55"]) else
            0.65 if any(x in age for x in ["18", "22"]) else
            1.0
        )
        income_mult = 1.3 if income > 0.7 else 0.8 if income < 0.3 else 1.0
        social_proof_threshold = int(
            (1 - trust) * 80 * (1 + risk_av * 0.5) * age_mult * income_mult
        )
        social_proof_threshold = max(0, social_proof_threshold)

        # ── Brand deficit penalty ─────────────────────────────────────────
        if brand_recognition == 0.0:
            brand_deficit_penalty = 0.65
        elif brand_recognition == 0.7:
            brand_deficit_penalty = 0.25
        elif brand_recognition == 1.0:
            brand_deficit_penalty = 0.05
        else:
            raw = max(0.05, (1 - brand_recognition) * 0.65)
            brand_deficit_penalty = raw * (
                1.4 if trust < 0.3 else 0.6 if trust > 0.7 else 1.0
            )
        brand_deficit_multiplier = 1.0 - brand_deficit_penalty

        # ── Other metrics ─────────────────────────────────────────────────
        product_type     = str(env_params.get("product_type", ""))
        security_concern = min(0.40, (1 - trust) * (1.6 if "health" in product_type else 1.0))

        founder_weight  = 0.60 if env_params.get("market_maturity", 0.5) < 0.4 else 0.25
        decay_rate      = skepticism * 0.4 * (
            1.5 if agent_profile.get("switching_friction", 0.5) < 0.4 else 0.6
        )
        recovery_days   = int(14 + decay_rate * 45 * (0.6 if patience > 0.6 else 1.5))

        testimonial_format = (
            "case_study" if literacy > 0.7 and income > 0.6 else
            "video"      if social > 0.6 else
            "written"
        )
        community_signal = social * 0.35 * (1.3 if trust < 0.5 else 0.6)
        press_lift       = 0.12 * (1.5 if literacy > 0.6 else 0.3)
        free_trial_sub   = min(0.75, risk_av * 0.4 * (
            1.5 if brand_deficit_multiplier < 0.7 else 0.8
        ))

        social_proof_met = (
            1.0 if reviews_current >= social_proof_threshold else
            (reviews_current / social_proof_threshold if social_proof_threshold > 0 else 1.0)
        )

        severity = (
            "CRITICAL" if brand_deficit_multiplier < 0.50 and social_proof_met < 0.3 else
            "WARNING"  if brand_deficit_multiplier < 0.75 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "social_proof_threshold":             float(social_proof_threshold),
                "brand_deficit_multiplier":           round(brand_deficit_multiplier, 4),
                "security_concern_intensity":         round(security_concern, 4),
                "founder_vs_product_credibility":     round(founder_weight, 4),
                "trust_decay_rate_per_incident":      round(decay_rate, 4),
                "trust_recovery_days":                float(recovery_days),
                "community_size_signal_weight":       round(community_signal, 4),
                "press_mention_lift":                 round(press_lift, 4),
                "free_trial_as_trust_substitute":     round(free_trial_sub, 4),
                "social_proof_met_fraction":          round(social_proof_met, 4),
            },
            flags={
                "brand_deficit_critical": brand_deficit_multiplier < 0.50,
                "social_proof_missing":   social_proof_met < 0.30,
                "free_trial_required":    free_trial_sub > 0.60,
                "testimonial_format":     testimonial_format == "case_study",
            },
            narrative_findings=[
                f"Brand deficit multiplier: {brand_deficit_multiplier:.2f}",
                f"Social proof needed: {social_proof_threshold} reviews, have {reviews_current}",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        bdm        = output.metrics.get("brand_deficit_multiplier", 0.8)
        sp_met     = output.metrics.get("social_proof_met_fraction", 1.0)
        free_trial = output.metrics.get("free_trial_as_trust_substitute", 0.3)
        trust_val  = bdm * sp_met
        return {
            ("BROWSE",   "CONSIDER"): max(0.05, min(0.95, trust_val)),
            ("CONSIDER", "DECIDE"):   max(0.05, min(0.95, bdm * (1 + free_trial * 0.3))),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("brand_deficit_critical")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(critical)} clusters blocked by brand deficit",
            affected_cluster_ids=[o.cluster_id for o in critical],
            population_fraction=round(len(critical) * 0.05, 3),
            conversion_impact=round(len(critical) * 0.04, 3),
            recommended_action="Add social proof, offer free trial, earn press mentions",
            severity="CRITICAL" if critical else "INFO",
        )
