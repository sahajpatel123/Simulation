"""
OnboardingArchitect — evaluates whether a cluster will complete onboarding.

Computes 11 onboarding-behavioural metrics from cluster traits, demographic
profile, and any complexity signals in assumptions.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition
from app.core.utils import geo_tier


class OnboardingArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "OnboardingArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "saas", "marketplace", "mobile_app",
            "developer_tool", "enterprise_software",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        literacy   = t["digital_literacy"]
        patience   = t["patience_score"]
        motivation = t["motivation"]
        trust      = t["trust"]
        geo        = geo_tier(cluster.demographic_profile.get("geography", "metro"))

        # ── Complexity from assumptions ──────────────────────────────────
        complexity = 0.5
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["complex", "advanced", "multi-step", "many features"]):
                complexity = 0.8
            elif any(w in text for w in ["simple", "easy", "quick", "seamless", "2 minute"]):
                complexity = 0.25

        # ── Core metrics ─────────────────────────────────────────────────

        base_completion = literacy * 0.4 + patience * 0.3 + motivation * 0.3
        completion = base_completion * (
            0.65 if complexity > 0.6 else
            0.85 if complexity < 0.3 else
            0.85
        )
        if geo in ("tier3", "tier3_rural"):
            completion *= 0.55
        elif geo in ("tier2", "tier1_tier2", "metro_tier1_tier2",
                     "metro_tier1_tier2_tier3", "tier1_tier2_tier3"):
            completion *= 0.82

        ttfv = patience * 8.0 + motivation * 4.0          # minutes
        if geo in ("tier3", "tier3_rural", "tier2",
                   "metro_tier1_tier2", "metro_tier1_tier2_tier3"):
            ttfv *= 0.75

        empty_bounce = (1 - motivation) * 0.5 * (1.4 if trust < 0.4 else 1.0)

        disclosure_limit = int(literacy * 12 + patience * 6)
        disclosure_limit = max(3, min(18, disclosure_limit))
        if geo in ("tier3", "tier3_rural"):
            disclosure_limit = min(disclosure_limit, 3)

        age = cluster.demographic_profile.get("age_bracket", "25-35")
        mobile_penalty = 0.0
        if complexity > 0.5:
            mobile_penalty = 0.20 if "18" in age else 0.12

        permission_sensitivity = (1 - trust) * 0.4
        mandatory_churn  = (1 - patience) * 0.25 * (1 - motivation * 0.4)
        video_skip       = 1.0 - (patience * 0.5 + literacy * 0.3) * (1 + motivation * 0.3)
        video_skip       = max(0.10, min(0.90, video_skip))
        social_lift      = trust * 0.2 * (1.3 if trust > 0.6 else 0.2)
        template_pref    = (1 - literacy) * 0.5 + (1 - motivation) * 0.2
        id_friction      = (1 - trust) * 0.25 * (1.4 if trust < 0.4 else 1.0)

        completion = max(0.05, min(0.98, completion))

        severity = (
            "CRITICAL" if completion < 0.40 else
            "WARNING"  if completion < 0.65 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "onboarding_completion_rate":     round(completion, 4),
                "time_to_first_value_tolerance":  round(ttfv, 2),
                "empty_state_bounce_probability": round(empty_bounce, 4),
                "progressive_disclosure_limit":   float(disclosure_limit),
                "mobile_completion_penalty":      round(mobile_penalty, 4),
                "permission_timing_sensitivity":  round(permission_sensitivity, 4),
                "mandatory_profile_churn_risk":   round(mandatory_churn, 4),
                "video_walkthrough_skip_rate":    round(video_skip, 4),
                "social_onboarding_lift":         round(social_lift, 4),
                "template_vs_blank_preference":   round(template_pref, 4),
                "identity_verification_friction": round(id_friction, 4),
            },
            flags={
                "completion_critical":    completion < 0.40,
                "mobile_gap_significant": mobile_penalty > 0.15,
                "empty_state_risky":      empty_bounce > 0.50,
                "tier3_language_risk":    geo in ("tier3", "tier3_rural"),
            },
            narrative_findings=[
                f"Onboarding completion: {completion * 100:.1f}%",
                f"Time tolerance: {ttfv:.1f} min, disclosure limit: {disclosure_limit} steps",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        completion  = output.metrics.get("onboarding_completion_rate", 0.7)
        id_friction = output.metrics.get("identity_verification_friction", 0.1)
        return {
            ("ARRIVE",  "BROWSE"):   max(0.05, min(0.98, completion)),
            ("BROWSE",  "CONSIDER"): max(0.05, 1.0 - id_friction),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.severity == "CRITICAL"]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(critical)} clusters have critical onboarding completion",
            affected_cluster_ids=[o.cluster_id for o in critical],
            population_fraction=round(len(critical) * 0.05, 3),
            conversion_impact=round(len(critical) * 0.025, 3),
            recommended_action="Simplify onboarding, add templates, reduce steps",
            severity="CRITICAL" if critical else "INFO",
        )
