"""
SupportFrictionArchitect — models post-purchase support load and churn risk.

Assumption-aware: complexity and knowledge-base signals in the brief
shape ticket likelihood, self-serve resolution and documentation
perception. Explicit ``agent_profile`` values (``product_complexity``,
``has_knowledge_base``) always win over assumption text.

No transition_overrides — feeds post-purchase churn modelling only.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.architects.utils import contains_word, extract_complexity
from app.simulation.clusters.definitions import ClusterDefinition

SUPPORTED_PRODUCT_TYPES: list[str] = [
    "saas", "marketplace", "mobile_app",
    "developer_tool", "enterprise_software",
    "consumer_hardware", "health_hardware",
    "iot_hardware", "wearable", "b2b_hardware",
    "consumer_app", "d2c", "b2b_marketplace",
    "productivity_tool", "smart_home",
]

# Phrases that tell the founder's brief whether a knowledge base /
# self-serve support surface exists. Absent-phrases are checked first so
# "no documentation" never matches the positive "documentation" token.
KB_PRESENT_PHRASES: list[str] = [
    "knowledge base", "knowledge_base", "help center", "help centre",
    "self-serve", "self serve", "faq", "help docs", "documentation",
    "docs", "onboarding guide", "support portal", "support team",
    "customer support", "chat support",
]
KB_ABSENT_PHRASES: list[str] = [
    "no knowledge base", "no knowledge_base", "no help center",
    "no help centre", "no documentation", "no docs", "no faq",
    "no support", "no self-serve", "no self serve", "no help",
    "no support team", "no customer support", "no chat support",
]


class SupportFrictionArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "SupportFrictionArchitect"

    @property
    def product_types(self) -> list[str]:
        # Every product category has a post-purchase support surface, so
        # the architect activates for all 15 product types.
        return SUPPORTED_PRODUCT_TYPES

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
        income     = t["income_level"]
        price_sens = t["price_sensitivity"]
        trust      = t["trust"]

        # ── Upstream context ──────────────────────────────────────────────
        # Explicit profile signals win; otherwise infer from the brief.
        try:
            complexity = float(agent_profile["product_complexity"])
        except (KeyError, TypeError, ValueError):
            complexity = extract_complexity(assumptions)
        onboard_cr  = agent_profile.get("onboarding_completion_rate", 0.65)
        if "has_knowledge_base" in agent_profile:
            has_knowledge_base = bool(agent_profile["has_knowledge_base"])
        else:
            has_knowledge_base = (
                not contains_word(assumptions, KB_ABSENT_PHRASES)
                and contains_word(assumptions, KB_PRESENT_PHRASES)
            )

        # ── Core metrics ──────────────────────────────────────────────────
        ticket_rate = min(0.70, (
            (1 - literacy) * 0.4
            + (1 - onboard_cr) * 0.4 * (1.6 if complexity > 0.6 else 0.7)
        ))

        kb_factor  = 1.3 if has_knowledge_base else 0.5
        self_serve = min(0.90, literacy * 0.7 * kb_factor)

        if income > 0.7:
            base_hours = 4.0
        elif income > 0.5:
            base_hours = 8.0
        else:
            base_hours = 24.0
        response_tolerance = base_hours * patience

        bug_tolerance = max(1, int(
            patience * 3
            * (0.7 if trust < 0.4 else 1.0)
            * (1.4 if price_sens < 0.3 else 0.8)
        ))

        downtime_sens = min(0.90, income * 0.6 + (1 - patience) * 0.3)

        # Escalation channel preference
        if income > 0.7:
            escalation = "phone"
        elif literacy > 0.6:
            escalation = "chat"
        elif literacy < 0.4:
            escalation = "phone"
        else:
            escalation = "email"

        doc_mult = 1.0 if has_knowledge_base else -0.25
        doc_effect = literacy * 0.3 * doc_mult

        severity = "WARNING" if ticket_rate > 0.35 else "INFO"

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "support_ticket_likelihood":               round(ticket_rate, 4),
                "self_serve_resolution_rate":              round(self_serve, 4),
                "response_time_tolerance_hours":           round(response_tolerance, 2),
                "bug_tolerance_threshold":                 float(bug_tolerance),
                "downtime_sensitivity":                    round(downtime_sens, 4),
                "documentation_quality_perception_effect": round(doc_effect, 4),
            },
            flags={
                "high_ticket_rate":       ticket_rate > 0.35,
                "low_self_serve":         self_serve < 0.30,
                "phone_support_required": escalation == "phone",
            },
            narrative_findings=[
                f"Support ticket rate: {ticket_rate * 100:.1f}%",
                f"Bug tolerance: {bug_tolerance} errors before abandonment",
                f"Escalation preference: {escalation}",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        high_friction = [o for o in outputs if o.flags.get("high_ticket_rate")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(high_friction)} clusters have high support friction",
            affected_cluster_ids=[o.cluster_id for o in high_friction],
            population_fraction=round(len(high_friction) * 0.05, 3),
            conversion_impact=round(len(high_friction) * 0.015, 3),
            recommended_action="Improve docs, add chat support, simplify error messages",
            severity="WARNING" if high_friction else "INFO",
        )
