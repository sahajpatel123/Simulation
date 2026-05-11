"""
AccountabilityEngine — distill many architect × cluster outputs into ranked,
benchmarked, founder-readable findings.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.simulation.conductor import ConductorResult
from app.simulation.clusters.registry import ClusterRegistry


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
    }

    LOWER_IS_BETTER: frozenset[str] = frozenset({
        "incumbent_switching_friction",
        "habit_loop_formation_days",
        "total_cascade_risk",
        "blind_spot_score",
        "empty_state_bounce_probability",
        "free_trial_as_trust_substitute",
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
