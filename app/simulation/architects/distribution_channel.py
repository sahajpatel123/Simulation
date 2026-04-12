"""
DistributionChannelArchitect — online/offline access, platform preference, and delivery expectations.

Includes ARRIVE→BROWSE and CONSIDER→DECIDE transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


def _patience_from(traits: dict) -> float:
    return float(traits.get("patience_score", 0.5))


def _geo_tier(geo: str) -> str:
    """Normalise compound geography strings to metro / tier2 / tier3."""
    geo = geo.lower()
    if "tier3" in geo or "rural" in geo:
        return "tier3"
    if "tier2" in geo:
        return "tier2"
    return "metro"


class DistributionChannelArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "DistributionChannelArchitect"

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
        literacy     = t["digital_literacy"]
        price_s      = t["price_sensitivity"]
        risk_av      = t["risk_aversion"]
        trust        = t["trust"]
        social       = t["social_orientation"]
        income       = t["income_level"]
        age          = cluster.demographic_profile.get("age_bracket", "25-35")
        geo          = _geo_tier(cluster.demographic_profile.get("geography", "metro"))
        AOV          = float(env_params.get("average_order_value", 3000))
        product_type = str(env_params.get("product_type", "consumer_hardware"))
        urgency      = float(agent_profile.get("problem_urgency_intensity", 0.5))

        # ── Extract assumptions ───────────────────────────────────────────
        offline_available = False
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in [
                "offline", "retail", "store", "physical distribution", "tier-2 available",
            ]):
                offline_available = True

        # ── Online preference ─────────────────────────────────────────────
        online_pref = (
            0.72 if geo == "metro" else
            0.55 if geo == "tier2" else
            0.35
        )
        online_pref *= (1.0 if AOV < 2000 else 0.85 if AOV > 15000 else 1.0)
        online_pref *= (0.75 if any(x in age for x in ["50", "55", "60"]) else 1.0)
        online_pref = max(0.05, min(0.95, online_pref))

        # ── Availability multiplier ───────────────────────────────────────
        if geo in ["tier2", "tier3"] and not offline_available:
            availability_multiplier = 0.55 if geo == "tier2" else 0.30
        else:
            availability_multiplier = 1.0

        # ── Delivery speed requirement (days) ────────────────────────────
        delivery_req = max(1, int(
            (1 if urgency > 0.8 else 5 if income < 0.3 else 2)
            * _patience_from(t)
        ))

        # ── Try before buy ────────────────────────────────────────────────
        try_before_buy = min(0.80,
            risk_av * 0.5
            * (1.5 if AOV > 5000 else 0.5 if AOV < 2000 else 1.0)
            * (
                1.8 if "researcher" in cluster.cluster_id else
                0.4 if "impulsive"  in cluster.cluster_id else
                1.0
            )
        )

        # ── Influencer dependency ─────────────────────────────────────────
        influencer_dep = min(0.80,
            (1 - trust) * social * 0.5
            * (
                1.4 if any(x in age for x in ["18", "22", "25", "28"]) else
                0.7 if any(x in age for x in ["45", "50"]) else
                1.0
            )
        )
        influencer_dep *= (1.6 if trust < 0.6 else 1.0)

        # ── Platform scores ───────────────────────────────────────────────
        cashback_sensitivity = min(0.70,
            price_s * 0.6 * (
                1.4 if income < 0.3 else
                0.5 if income > 0.7 else
                1.0
            )
        )

        amazon_score   = min(1.0, literacy * 0.6 * (1.2 if geo == "metro" else 0.9))
        flipkart_score = min(1.0, literacy * 0.5 * (1.4 if geo in ["tier2", "tier3"] else 0.9))
        brand_direct   = min(0.60, trust * 0.4 * (1.3 if risk_av > 0.6 else 0.8))
        offline_score  = min(0.80, (1 - online_pref) * 1.5)

        severity = (
            "CRITICAL" if availability_multiplier < 0.40 else
            "WARNING"  if try_before_buy > 0.60 and AOV > 5000 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "online_preference":                     round(online_pref, 4),
                "distribution_accessibility_multiplier": round(availability_multiplier, 4),
                "delivery_speed_days_required":          float(delivery_req),
                "try_before_buy_requirement":            round(try_before_buy, 4),
                "influencer_review_dependency":          round(influencer_dep, 4),
                "cashback_loyalty_sensitivity":          round(cashback_sensitivity, 4),
                "platform_pref_amazon":                  round(amazon_score, 4),
                "platform_pref_flipkart":                round(flipkart_score, 4),
                "platform_pref_brand_direct":            round(brand_direct, 4),
                "platform_pref_offline":                 round(offline_score, 4),
            },
            flags={
                "distribution_kill_shot":  availability_multiplier < 0.40,
                "try_before_buy_critical": try_before_buy > 0.60 and AOV > 5000,
                "influencer_required":     influencer_dep > 0.55,
                "cashback_sensitive":      cashback_sensitivity > 0.50,
            },
            narrative_findings=[
                f"Online pref: {online_pref * 100:.1f}% | Availability mult: {availability_multiplier:.2f}",
                f"Influencer dependency: {influencer_dep * 100:.1f}%",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        avail = output.metrics.get("distribution_accessibility_multiplier", 1.0)
        tbuy  = output.metrics.get("try_before_buy_requirement", 0.3)
        return {
            ("ARRIVE",   "BROWSE"):  max(0.05, min(0.95, avail)),
            ("CONSIDER", "DECIDE"):  max(0.05, min(0.95, 1.0 - tbuy * 0.4)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        kill = [o for o in outputs if o.flags.get("distribution_kill_shot")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(kill)} clusters cannot access product (offline unavailable)",
            affected_cluster_ids=[o.cluster_id for o in kill],
            population_fraction=round(len(kill) * 0.06, 3),
            conversion_impact=round(len(kill) * 0.07, 3),
            recommended_action="Establish offline distribution for Tier-2/Tier-3 segments",
            severity="CRITICAL" if kill else "INFO",
        )
