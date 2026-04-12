"""
CompetitiveDynamicsArchitect — sets competitive barrier baseline for each cluster.

Runs SECOND in the Conductor stack, after MarketTimingArchitect.
Consumes switching_cost_depth and problem_urgency_intensity from upstream
(passed via agent_profile by the Conductor).
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class CompetitiveDynamicsArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "CompetitiveDynamicsArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "saas", "marketplace", "mobile_app", "developer_tool",
            "enterprise_software", "consumer_hardware", "health_hardware",
            "iot_hardware", "wearable", "b2b_hardware",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        risk_av    = t["risk_aversion"]
        literacy   = t["digital_literacy"]
        price_sens = t["price_sensitivity"]
        trust      = t["trust"]
        loyalty    = 0.5   # default; refined by calibration

        market_maturity = float(env_params.get("market_maturity", 0.5))
        switching_cost  = float(agent_profile.get("switching_cost_depth", 0.5))
        urgency         = float(agent_profile.get("problem_urgency_intensity", 0.5))

        # ── Extract competitive signals from assumptions ───────────────────
        competitor_type       = "paid_only"
        differentiation_level = 0.5
        feature_completion    = 0.5

        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["free competitor", "free alternative", "open source"]):
                competitor_type = "free"
            elif any(w in text for w in ["no competitor", "no alternative", "new category"]):
                competitor_type = "none"
            if any(w in text for w in ["unique", "differentiated", "10x better", "only one"]):
                differentiation_level = 0.85
            elif any(w in text for w in ["similar to", "like", "alternative to"]):
                differentiation_level = 0.35
            if any(w in text for w in ["feature complete", "full featured", "all features"]):
                feature_completion = 0.90
            elif any(w in text for w in ["mvp", "basic", "limited", "early"]):
                feature_completion = 0.35

        # ── Switching friction ────────────────────────────────────────────
        competitor_mult = {"free": 1.5, "none": 0.2, "paid_only": 1.0}.get(competitor_type, 1.0)
        switching_friction = min(0.95, switching_cost * competitor_mult * (
            1.3 if risk_av > 0.7 else 0.9
        ))

        # ── Feature parity ────────────────────────────────────────────────
        sophistication = literacy * 0.6 + (1 - risk_av) * 0.4
        parity_threshold = (
            0.85 if market_maturity > 0.7 else
            0.65 if market_maturity > 0.4 else
            0.20 if competitor_type == "none" else
            0.45
        ) * (1.2 if sophistication > 0.7 else 0.7 if sophistication < 0.3 else 1.0)
        parity_threshold = min(0.95, parity_threshold)
        feature_parity_met = feature_completion >= parity_threshold

        # ── Derived competitive metrics ───────────────────────────────────
        price_undercutting = (1 - switching_friction) * 0.6 * (
            1.4 if price_sens > 0.7 else 0.6
        )

        niche_pref    = 0.75 if sophistication > 0.6 else 0.35
        best_of_breed = 0.80 if sophistication > 0.6 else 0.35
        multi_vendor  = min(0.80, (1 - risk_av) * sophistication)

        displacement_days = int(switching_friction * 90 * (0.5 if urgency > 0.7 else 1.5))
        displacement_days = max(3, displacement_days)

        loss_aversion = min(0.90, risk_av * 0.8 * (
            1.4 if switching_friction > 0.6 else 0.8
        ))
        brand_loyalty = min(0.85, trust * loyalty * (
            1.3 if market_maturity > 0.6 else 0.8
        ))

        severity = (
            "CRITICAL" if switching_friction > 0.75 and not feature_parity_met else
            "WARNING"  if switching_friction > 0.50 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "incumbent_switching_friction":      round(switching_friction, 4),
                "feature_parity_threshold":          round(parity_threshold, 4),
                "feature_parity_met":                1.0 if feature_parity_met else 0.0,
                "price_undercutting_response":       round(price_undercutting, 4),
                "niche_vs_broad_preference":         round(niche_pref, 4),
                "best_of_breed_vs_all_in_one":       round(best_of_breed, 4),
                "multi_vendor_tolerance":            round(multi_vendor, 4),
                "competitive_displacement_days":     float(displacement_days),
                "loss_aversion_magnitude":           round(loss_aversion, 4),
                "competitor_brand_loyalty_strength": round(brand_loyalty, 4),
            },
            flags={
                "switching_friction_critical": switching_friction > 0.75,
                "feature_parity_not_met":      not feature_parity_met,
                "free_competitor_present":     competitor_type == "free",
                "no_competition":              competitor_type == "none",
            },
            narrative_findings=[
                f"Switching friction: {switching_friction:.2f} | Parity met: {feature_parity_met}",
                f"Displacement timeline: {displacement_days} days",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        friction   = output.metrics.get("incumbent_switching_friction", 0.5)
        parity_met = output.metrics.get("feature_parity_met", 1.0)
        loss_av    = output.metrics.get("loss_aversion_magnitude", 0.4)
        consider_decide = max(0.05, min(0.95,
            (1 - friction) * (parity_met if parity_met > 0 else 0.15)
        ))
        decide_abandon_penalty = min(0.60, loss_av * 0.3)
        return {
            ("CONSIDER", "DECIDE"):  consider_decide,
            ("DECIDE",   "ABANDON"): decide_abandon_penalty,
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical  = [o for o in outputs if o.flags.get("switching_friction_critical")]
        no_parity = [o for o in outputs if o.flags.get("feature_parity_not_met")]
        affected  = list({o.cluster_id for o in critical + no_parity})
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters have critical switching friction; "
                f"{len(no_parity)} below feature parity"
            ),
            affected_cluster_ids=affected,
            population_fraction=round((len(critical) + len(no_parity)) * 0.04, 3),
            conversion_impact=round(len(critical) * 0.05, 3),
            recommended_action="Improve feature parity, reduce switching cost, offer migration tools",
            severity=(
                "CRITICAL" if critical else
                "WARNING"  if no_parity else
                "INFO"
            ),
        )
