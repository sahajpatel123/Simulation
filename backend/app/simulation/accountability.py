"""
AccountabilityEngine — distill many architect × cluster outputs into ranked,
benchmarked, founder-readable findings.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import ConductorResult


@dataclass
class DomainFinding:
    architect_name: str
    cluster_id: str
    cluster_name: str
    cluster_population_fraction: float
    finding: str
    metric_affected: str
    actual_value: float
    healthy_benchmark: float
    delta_from_benchmark: float
    impact_on_overall_conversion: float
    recommended_action: str
    affected_agent_count: int
    severity: str  # INFO | WARNING | CRITICAL

    def to_dict(self) -> dict:
        return {
            "architect_name": self.architect_name,
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "population_fraction": round(self.cluster_population_fraction, 4),
            "finding": self.finding,
            "metric_affected": self.metric_affected,
            "actual_value": round(self.actual_value, 4),
            "healthy_benchmark": round(self.healthy_benchmark, 4),
            "delta": round(self.delta_from_benchmark, 4),
            "conversion_impact": round(self.impact_on_overall_conversion, 4),
            "recommended_action": self.recommended_action,
            "affected_agent_count": self.affected_agent_count,
            "severity": self.severity,
        }


class AccountabilityEngine:

    HEALTHY_BENCHMARKS: dict[str, float] = {
        "onboarding_completion_rate": 0.65,
        "empty_state_bounce_probability": 0.25,
        "day1_survival": 0.45,
        "day7_survival": 0.35,
        "day30_survival": 0.20,
        "day90_survival": 0.12,
        "habit_loop_formation_days": 30.0,
        "will_pay_probability": 0.40,
        "freemium_conversion_ceiling": 0.06,
        "annual_payment_probability": 0.25,
        "brand_deficit_multiplier": 0.75,
        "social_proof_met_fraction": 0.70,
        "free_trial_as_trust_substitute": 0.30,
        "incumbent_switching_friction": 0.45,
        "feature_parity_met": 1.0,
        "category_awareness_score": 0.60,
        "problem_urgency_intensity": 0.55,
        "feature_depth_score": 0.40,
        "core_feature_dau_rate": 0.55,
        "viral_coefficient": 0.10,
        "organic_referral_trigger_score": 0.05,
        "oob_setup_completion_rate": 0.80,
        "distribution_accessibility_multiplier": 0.80,
        "clinical_gate_multiplier": 1.0,
        "total_cascade_risk": 0.20,
        "blind_spot_score": 0.0,
        "privacy_concern_intensity": 0.25,
        "certification_barrier": 0.30,
        "refund_liability_concern": 0.30,
        "regulatory_suppressor": 1.0,
        "compliance_credibility": 1.0,
        "payment_method_coverage": 0.80,
        "checkout_friction": 0.20,
        "payment_credibility": 1.0,
        "cash_gap_active": 0.0,
        "financing_gap_active": 0.0,
        "disability_barrier": 0.30,
        "language_barrier": 0.25,
        "age_friction": 0.35,
        "accessibility_credibility": 1.0,
        "funnel_suppressor": 1.0,
        "procurement_friction": 0.30,
        "security_review_barrier": 0.25,
        "vendor_list_barrier": 0.20,
        "procurement_cycle_days": 30.0,
        "poc_requirement": 0.30,
        "procurement_credibility": 1.0,
        "platform_dependency_exposure": 0.15,
        "dependency_concentration": 0.25,
        "single_channel_risk": 0.10,
        "platform_gate_risk": 0.20,
        "platform_risk_score": 0.25,
        "platform_risk_suppressor": 1.0,
        "mitigation_credibility": 1.0,
        "viability_exposure": 0.15,
        "business_health_score": 0.80,
        "viability_risk": 0.20,
        "runway_funnel_suppressor": 1.0,
        "messaging_clarity_score": 0.70,
        "comprehension_risk": 0.25,
        "vague_language_density": 0.10,
        "clarity_funnel_suppressor": 1.0,
        "execution_credibility_score": 0.70,
        "delivery_risk": 0.25,
        "execution_funnel_suppressor": 1.0,
        "ai_risk_load": 0.30,
        "ai_skepticism": 0.40,
        "ai_mitigation_credibility": 1.0,
        "perceived_ai_risk": 0.20,
        "ai_trust_gap": 0.20,
        "ai_funnel_suppressor": 1.0,
    }

    LOWER_IS_BETTER: frozenset[str] = frozenset({
        "incumbent_switching_friction",
        "habit_loop_formation_days",
        "total_cascade_risk",
        "blind_spot_score",
        "empty_state_bounce_probability",
        "free_trial_as_trust_substitute",
        "privacy_concern_intensity",
        "certification_barrier",
        "refund_liability_concern",
        "checkout_friction",
        "cash_gap_active",
        "financing_gap_active",
        "disability_barrier",
        "language_barrier",
        "age_friction",
        "procurement_friction",
        "security_review_barrier",
        "vendor_list_barrier",
        "procurement_cycle_days",
        "poc_requirement",
        "platform_dependency_exposure",
        "dependency_concentration",
        "single_channel_risk",
        "platform_gate_risk",
        "platform_risk_score",
        "viability_exposure",
        "viability_risk",
        "comprehension_risk",
        "vague_language_density",
        "delivery_risk",
        "ai_risk_load",
        "ai_skepticism",
        "perceived_ai_risk",
        "ai_trust_gap",
    })

    FINDING_TEMPLATES: dict[str, str] = {
        "onboarding_completion_rate": (
            "{pct:.0f}% of {cluster} complete onboarding (benchmark {bench:.0f}%)"
        ),
        "day7_survival": (
            "{pct:.0f}% of {cluster} return at day-7 (benchmark {bench:.0f}%)"
        ),
        "day30_survival": (
            "{pct:.0f}% of {cluster} survive to day-30 (benchmark {bench:.0f}%)"
        ),
        "will_pay_probability": (
            "{pct:.0f}% of {cluster} will pay at current price (benchmark {bench:.0f}%)"
        ),
        "brand_deficit_multiplier": (
            "{cluster} conversion reduced {pct:.0f}% by unknown brand"
        ),
        "incumbent_switching_friction": (
            "{cluster} has {val:.2f} switching friction (threshold {bench:.2f})"
        ),
        "category_awareness_score": (
            "Only {pct:.0f}% of {cluster} understand the category (benchmark {bench:.0f}%)"
        ),
        "feature_depth_score": (
            "{cluster} feature depth {val:.2f} — shallow adoption risk"
        ),
        "oob_setup_completion_rate": (
            "Only {pct:.0f}% of {cluster} complete hardware setup (benchmark {bench:.0f}%)"
        ),
        "distribution_accessibility_multiplier": (
            "{cluster} accessibility {val:.2f} — distribution gap"
        ),
        "clinical_gate_multiplier": (
            "{cluster} blocked: clinical validation missing"
        ),
        "total_cascade_risk": (
            "Assumption cascade risk {val:.2f} for {cluster}"
        ),
        "viral_coefficient": (
            "{cluster} K-factor {val:.3f} — below viral threshold"
        ),
        "social_proof_met_fraction": (
            "Only {pct:.0f}% of {cluster} social proof requirement met"
        ),
        "privacy_concern_intensity": (
            "{pct:.0f}% of {cluster} blocked by data-privacy concerns "
            "(benchmark {bench:.0f}%)"
        ),
        "certification_barrier": (
            "{cluster} faces certification/approval barrier {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "refund_liability_concern": (
            "{pct:.0f}% of {cluster} worry about refunds/liability "
            "(benchmark {bench:.0f}%)"
        ),
        "regulatory_suppressor": (
            "Regulatory exposure leaves {cluster} at {pct:.0f}% funnel "
            "strength (benchmark {bench:.0f}%)"
        ),
        "compliance_credibility": (
            "{cluster} sees weak compliance credibility "
            "({val:.2f} vs benchmark {bench:.2f})"
        ),
        "payment_method_coverage": (
            "Only {pct:.0f}% of {cluster} have compatible payment methods "
            "(benchmark {bench:.0f}%)"
        ),
        "checkout_friction": (
            "Checkout friction for {cluster} is {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "cash_dependency": (
            "{pct:.0f}% of {cluster} depend on cash/COD payments "
            "(benchmark {bench:.0f}%)"
        ),
        "financing_dependency": (
            "{pct:.0f}% of {cluster} need EMI/BNPL/invoice financing "
            "(benchmark {bench:.0f}%)"
        ),
        "payment_credibility": (
            "{cluster} sees weak payment credibility "
            "({val:.2f} vs benchmark {bench:.2f})"
        ),
        "cash_gap_active": (
            "{cluster} has an open cash/COD payment gap "
            "(benchmark {bench:.2f})"
        ),
        "financing_gap_active": (
            "{cluster} has an open financing gap (EMI/BNPL/invoice) "
            "(benchmark {bench:.2f})"
        ),
        "disability_barrier": (
            "{cluster} faces disability/accessibility barrier {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "language_barrier": (
            "{cluster} faces language/localization barrier {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "age_friction": (
            "{cluster} faces senior/age friction {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "accessibility_credibility": (
            "{cluster} sees weak accessibility credibility "
            "({val:.2f} vs benchmark {bench:.2f})"
        ),
        "funnel_suppressor": (
            "Inclusion gaps leave {cluster} at {pct:.0f}% funnel "
            "strength (benchmark {bench:.0f}%)"
        ),
        "procurement_friction": (
            "{cluster} procurement friction {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "security_review_barrier": (
            "{cluster} faces security-review barrier {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "vendor_list_barrier": (
            "{cluster} blocked by vendor-list/approval barrier {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "procurement_cycle_days": (
            "{cluster} procurement cycle runs {val:.0f} days "
            "(benchmark {bench:.0f})"
        ),
        "poc_requirement": (
            "{pct:.0f}% of {cluster} require PoC/pilot before purchase "
            "(benchmark {bench:.0f}%)"
        ),
        "procurement_credibility": (
            "{cluster} sees weak procurement credibility "
            "({val:.2f} vs benchmark {bench:.2f})"
        ),
        "platform_dependency_exposure": (
            "{pct:.0f}% of {cluster} exposed to platform dependence "
            "(benchmark {bench:.0f}%)"
        ),
        "dependency_concentration": (
            "{cluster} platform concentration {val:.2f} (benchmark {bench:.2f})"
        ),
        "single_channel_risk": (
            "{cluster} single-channel platform risk {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "platform_gate_risk": (
            "{cluster} faces store/algorithm/API gate risk {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "platform_risk_score": (
            "{cluster} platform dependence risk {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "platform_risk_suppressor": (
            "Platform dependence leaves {cluster} at {pct:.0f}% funnel "
            "strength (benchmark {bench:.0f}%)"
        ),
        "mitigation_credibility": (
            "{cluster} sees weak platform mitigation credibility "
            "({val:.2f} vs benchmark {bench:.2f})"
        ),
        "viability_exposure": (
            "{pct:.0f}% of {cluster} exposed to cash-runway uncertainty "
            "(benchmark {bench:.0f}%)"
        ),
        "business_health_score": (
            "{cluster} sees {pct:.0f}% viability confidence "
            "(benchmark {bench:.0f}%)"
        ),
        "viability_risk": (
            "{cluster} faces viability risk {val:.2f} "
            "(benchmark {bench:.2f})"
        ),
        "runway_funnel_suppressor": (
            "Cash-runway uncertainty leaves {cluster} at {pct:.0f}% funnel "
            "strength (benchmark {bench:.0f}%)"
        ),
        "messaging_clarity_score": (
            "{cluster} understands only {pct:.0f}% of the value proposition "
            "(benchmark {bench:.0f}%)"
        ),
        "comprehension_risk": (
            "{cluster} faces {pct:.0f}% comprehension risk from unclear "
            "messaging (benchmark {bench:.0f}%)"
        ),
        "vague_language_density": (
            "{cluster} sees {pct:.0f}% hype language in the pitch "
            "(benchmark {bench:.0f}%)"
        ),
        "clarity_funnel_suppressor": (
            "Unclear messaging leaves {cluster} at {pct:.0f}% funnel "
            "strength (benchmark {bench:.0f}%)"
        ),
        "execution_credibility_score": (
            "{cluster} sees only {pct:.0f}% execution credibility "
            "(benchmark {bench:.0f}%)"
        ),
        "delivery_risk": (
            "{cluster} faces {pct:.0f}% delivery risk from weak "
            "team/prototype evidence (benchmark {bench:.0f}%)"
        ),
        "execution_funnel_suppressor": (
            "Weak execution evidence leaves {cluster} at {pct:.0f}% "
            "purchase funnel strength (benchmark {bench:.0f}%)"
        ),
        "ai_risk_load": (
            "{cluster} carries {pct:.0f}% AI risk exposure from the "
            "pitch (benchmark {bench:.0f}%)"
        ),
        "ai_skepticism": (
            "{cluster} scores {pct:.0f}% AI skepticism "
            "(benchmark {bench:.0f}%)"
        ),
        "ai_mitigation_credibility": (
            "{cluster} sees only {pct:.0f}% AI trust mitigation "
            "(benchmark {bench:.0f}%)"
        ),
        "perceived_ai_risk": (
            "{cluster} perceives {pct:.0f}% AI risk "
            "(benchmark {bench:.0f}%)"
        ),
        "ai_trust_gap": (
            "{cluster} has a {pct:.0f}% AI trust gap "
            "(benchmark {bench:.0f}%)"
        ),
        "ai_funnel_suppressor": (
            "AI skepticism leaves {cluster} at {pct:.0f}% purchase "
            "funnel strength (benchmark {bench:.0f}%)"
        ),
    }

    RECOMMENDED_ACTIONS: dict[str, str] = {
        "onboarding_completion_rate": "Simplify onboarding, add templates, reduce steps",
        "day7_survival": "Improve time-to-value, add habit triggers",
        "day30_survival": "Add gamification, content freshness, re-engagement",
        "will_pay_probability": "Lower price, add EMI option, or add free tier",
        "brand_deficit_multiplier": "Add reviews, press mentions, free trial",
        "incumbent_switching_friction": "Build migration tools, reduce switching cost",
        "category_awareness_score": "Invest in category education content",
        "feature_depth_score": "Add progressive feature discovery, guided tours",
        "oob_setup_completion_rate": "Simplify setup, add printed guide",
        "distribution_accessibility_multiplier": "Add offline distribution for Tier-2/Tier-3",
        "clinical_gate_multiplier": "Obtain CDSCO/BIS clinical validation",
        "total_cascade_risk": "Validate critical assumptions with real users",
        "viral_coefficient": "Build referral programme, create shareable outputs",
        "social_proof_met_fraction": "Collect reviews, publish case studies",
        "privacy_concern_intensity": (
            "Publish a clear privacy policy, add opt-in consent and "
            "data minimisation"
        ),
        "certification_barrier": (
            "Map and obtain required certifications/approvals before scaling"
        ),
        "refund_liability_concern": (
            "Add a transparent refund/returns and warranty policy"
        ),
        "regulatory_suppressor": (
            "Resolve the regulatory pathway: licences, approvals, "
            "compliance filings"
        ),
        "compliance_credibility": (
            "Publish compliance evidence: certifications, audits, policy pages"
        ),
        "payment_method_coverage": (
            "Accept the payment methods each segment uses: UPI, COD, cards, "
            "wallets, EMI/BNPL, invoices and international payments"
        ),
        "checkout_friction": (
            "Simplify checkout and remove restricted/required payment methods"
        ),
        "cash_dependency": (
            "Add cash-on-delivery or offline/cash payment options for "
            "cash-dependent segments"
        ),
        "financing_dependency": (
            "Add EMI, BNPL, installment plans or invoice/net terms for "
            "high-AOV buyers"
        ),
        "payment_credibility": (
            "Publish payment-method evidence: supported methods, gateways "
            "and international coverage"
        ),
        "cash_gap_active": (
            "Add cash-on-delivery or offline/cash payment options for "
            "cash-dependent segments"
        ),
        "financing_gap_active": (
            "Add EMI, BNPL, installment plans or invoice/net terms for "
            "high-AOV buyers"
        ),
        "disability_barrier": (
            "Ship WCAG-aligned design, screen-reader/keyboard support and captions"
        ),
        "language_barrier": (
            "Localize the product and onboarding into regional languages"
        ),
        "age_friction": (
            "Add large-text, senior-friendly onboarding and simple mode"
        ),
        "accessibility_credibility": (
            "Publish accessibility evidence: audits, statement, compliance notes"
        ),
        "funnel_suppressor": (
            "Close inclusion gaps (disability, language, age) and publish evidence"
        ),
        "procurement_friction": (
            "Publish SOC 2/security evidence, MSA/DPA templates, and a "
            "PoC/pilot path"
        ),
        "security_review_barrier": (
            "Publish security review evidence: SOC 2, ISO 27001, pen-test reports"
        ),
        "vendor_list_barrier": (
            "Complete vendor onboarding, MSA/DPA templates, and procurement sign-off"
        ),
        "procurement_cycle_days": (
            "Shorten procurement cycle with self-serve trials and pre-approved contracts"
        ),
        "poc_requirement": (
            "Offer structured PoC/pilot with reference customers to clear evaluation"
        ),
        "procurement_credibility": (
            "Publish procurement evidence: security reports, signed contracts, case studies"
        ),
        "platform_dependency_exposure": (
            "Diversify distribution and infrastructure: web-first/PWA access, "
            "owned email list, multi-channel acquisition, multi-cloud/API fallbacks"
        ),
        "dependency_concentration": (
            "Reduce platform concentration with alternative stores, channels "
            "and providers"
        ),
        "single_channel_risk": (
            "Remove single-platform dependence with an owned channel "
            "(web/PWA, email list, direct sales)"
        ),
        "platform_gate_risk": (
            "Address the app-store/algorithm/API gate with owned channels "
            "and provider fallbacks"
        ),
        "platform_risk_score": (
            "Diversify away from store, algorithm and API concentration "
            "before scaling"
        ),
        "platform_risk_suppressor": (
            "Publish platform mitigations: web/PWA access, owned channels, "
            "multi-provider setup"
        ),
        "mitigation_credibility": (
            "Ship and document mitigations: web app/PWA, email list, "
            "multi-cloud, portability"
        ),
        "viability_exposure": (
            "Publish funding, revenue and runway evidence so buyers stop "
            "discounting for shutdown risk"
        ),
        "business_health_score": (
            "Show 12-18 months of runway, revenue traction or breakeven "
            "unit economics"
        ),
        "viability_risk": (
            "Extend cash runway and share unit economics with high-risk, "
            "high-ticket clusters"
        ),
        "runway_funnel_suppressor": (
            "Publish concrete funding/revenue/runway evidence and a "
            "12-18 month cash plan"
        ),
        "messaging_clarity_score": (
            "Rewrite the pitch in plain language: one sentence on who it "
            "is for, what it does, and one quantified outcome"
        ),
        "comprehension_risk": (
            "Test the landing page copy with low-literacy segments and "
            "simplify jargon"
        ),
        "vague_language_density": (
            "Replace hype words with concrete outcomes, numbers and a "
            "named audience"
        ),
        "clarity_funnel_suppressor": (
            "Add a plain-language one-liner and concrete proof points "
            "above the fold"
        ),
        "execution_credibility_score": (
            "Publish team, prototype and support evidence on the landing page"
        ),
        "delivery_risk": (
            "Ship a working prototype or live MVP, add named technical "
            "leadership, and publish a support plan"
        ),
        "execution_funnel_suppressor": (
            "Add execution proof points (prototype, beta users, team, "
            "support) above the fold"
        ),
        "ai_risk_load": (
            "Reduce AI opacity: name human oversight and explainable "
            "decisions in the pitch"
        ),
        "ai_skepticism": (
            "Target skeptical segments with concrete AI accuracy and "
            "audit evidence"
        ),
        "ai_mitigation_credibility": (
            "Add human fallback, explainability, and data-control opt-outs"
        ),
        "perceived_ai_risk": (
            "Publish AI accuracy benchmarks and a human escalation path"
        ),
        "ai_trust_gap": (
            "Publish AI trust evidence (human review, fact-checking, "
            "opt-outs) above the fold"
        ),
        "ai_funnel_suppressor": (
            "Add human fallback, fact-checking, and data opt-outs to "
            "restore purchase confidence"
        ),
    }

    def __init__(self) -> None:
        self._registry = ClusterRegistry()

    def generate_domain_findings(
        self,
        conductor_result: ConductorResult,
        total_agents: int = 10000,
    ) -> list[DomainFinding]:
        findings: list[DomainFinding] = []
        clusters = {c.cluster_id: c for c in self._registry.all_clusters()}
        pwc = conductor_result.population_weighted_conversion or 0.01

        for cluster_id, arch_outputs in conductor_result.cluster_results.items():
            cluster_def = clusters.get(cluster_id)
            if not cluster_def:
                continue
            pop_frac = cluster_def.population_weight
            agent_count = int(pop_frac * total_agents)
            cluster_cr = conductor_result.cluster_breakdown.get(cluster_id, 0.0)

            for arch_name, output in arch_outputs.items():
                for metric_key, raw_val in output.metrics.items():
                    if metric_key not in self.HEALTHY_BENCHMARKS:
                        continue
                    if not isinstance(raw_val, (int, float)):
                        continue
                    actual_val = float(raw_val)
                    benchmark = self.HEALTHY_BENCHMARKS[metric_key]
                    lower_is_better = metric_key in self.LOWER_IS_BETTER

                    if lower_is_better:
                        delta = actual_val - benchmark
                        is_bad = delta > 0 and (delta / max(benchmark, 0.001)) > 0.20
                    else:
                        delta = benchmark - actual_val
                        is_bad = delta > 0 and (delta / max(benchmark, 0.001)) > 0.20

                    if not is_bad:
                        continue

                    conversion_impact = round(
                        abs(delta) * pop_frac * (cluster_cr / max(pwc, 0.001)), 4
                    )
                    if conversion_impact <= 0.0:
                        conversion_impact = 0.0001
                    conversion_impact = min(0.50, conversion_impact)

                    severity = (
                        "CRITICAL"
                        if abs(delta) / max(benchmark, 0.001) > 0.50
                        else "WARNING"
                    )

                    template = self.FINDING_TEMPLATES.get(
                        metric_key,
                        f"{metric_key} = {actual_val:.3f} (benchmark {benchmark:.3f})",
                    )
                    bench_fmt = benchmark * 100 if benchmark <= 1.0 else benchmark
                    try:
                        finding_text = template.format(
                            cluster=cluster_def.name,
                            pct=actual_val * 100,
                            val=actual_val,
                            bench=bench_fmt,
                        )
                    except Exception:
                        finding_text = f"{metric_key}: {actual_val:.3f} vs benchmark {benchmark:.3f}"

                    findings.append(
                        DomainFinding(
                            architect_name=arch_name,
                            cluster_id=cluster_id,
                            cluster_name=cluster_def.name,
                            cluster_population_fraction=pop_frac,
                            finding=finding_text,
                            metric_affected=metric_key,
                            actual_value=actual_val,
                            healthy_benchmark=benchmark,
                            delta_from_benchmark=round(delta, 4),
                            impact_on_overall_conversion=conversion_impact,
                            recommended_action=self.RECOMMENDED_ACTIONS.get(
                                metric_key, "Review and improve this metric"
                            ),
                            affected_agent_count=agent_count,
                            severity=severity,
                        )
                    )

        return self.rank_by_impact(findings)

    def rank_by_impact(
        self,
        findings: list[DomainFinding],
    ) -> list[DomainFinding]:
        return sorted(
            findings,
            key=lambda f: (
                0 if f.severity == "CRITICAL" else 1,
                -f.impact_on_overall_conversion,
            ),
        )

    def primary_failure_domain(
        self,
        findings: list[DomainFinding],
    ) -> str:
        if not findings:
            return "unknown"
        arch_impact: dict[str, float] = {}
        ranked_findings = [f for f in findings if f.severity == "CRITICAL"] or findings
        for f in ranked_findings:
            arch_impact[f.architect_name] = (
                arch_impact.get(f.architect_name, 0.0) + f.impact_on_overall_conversion
            )
        if not arch_impact:
            return "unknown"
        return max(arch_impact, key=arch_impact.get)

    def highest_value_cluster(
        self,
        conductor_result: ConductorResult,
    ) -> tuple[str, float]:
        clusters = {c.cluster_id: c for c in self._registry.all_clusters()}
        if not conductor_result.cluster_breakdown:
            return ("unknown", 0.0)
        best_id = max(
            conductor_result.cluster_breakdown,
            key=lambda k: conductor_result.cluster_breakdown.get(k, 0.0),
        )
        best_name = clusters[best_id].name if best_id in clusters else best_id
        return (best_name, conductor_result.cluster_breakdown[best_id])

    def generate_cluster_breakdown_narrative(
        self,
        conductor_result: ConductorResult,
        top_n: int = 5,
    ) -> str:
        clusters = {c.cluster_id: c for c in self._registry.all_clusters()}
        breakdown = conductor_result.cluster_breakdown
        sorted_clusters = sorted(breakdown.items(), key=lambda x: -x[1])

        lines = [
            f"Overall conversion: {conductor_result.population_weighted_conversion * 100:.1f}%",
            f"Product type: {conductor_result.product_type.value}",
            "",
            "Top converting segments:",
        ]
        for cid, cr in sorted_clusters[:top_n]:
            cdef = clusters.get(cid)
            name = cdef.name if cdef else cid
            pop = cdef.population_weight if cdef else 0.0
            lines.append(f"  {name}: {cr * 100:.1f}% conversion ({pop * 100:.1f}% of market)")

        lines.append("")
        lines.append("Lowest converting segments:")
        for cid, cr in sorted_clusters[-3:]:
            cdef = clusters.get(cid)
            name = cdef.name if cdef else cid
            pop = cdef.population_weight if cdef else 0.0
            lines.append(f"  {name}: {cr * 100:.1f}% conversion ({pop * 100:.1f}% of market)")

        primary = self.primary_failure_domain(self.generate_domain_findings(conductor_result))
        lines.append(f"\nPrimary failure domain: {primary}")
        hv_name, hv_cr = self.highest_value_cluster(conductor_result)
        lines.append(
            f"Highest value acquisition target: {hv_name} ({hv_cr * 100:.1f}% conversion)"
        )

        return "\n".join(lines)
