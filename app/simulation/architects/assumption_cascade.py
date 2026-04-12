"""
AssumptionCascadeArchitect — correlates critical assumptions and cascade risk across domains.

Runs LAST in the Conductor stack as a correction layer. No transition overrides.
Consumes optional float scores in agent_profile (e.g. viral_coefficient).
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

ASSUMPTION_CORRELATION_MAP: dict[tuple[str, str], float] = {
    ("pricing", "retention"):      0.72,
    ("trust", "competitive"):      0.65,
    ("timing", "pricing"):         0.58,
    ("onboarding", "trust"):       0.28,
    ("distribution", "pricing"):   0.45,
    ("performance", "trust"):      0.50,
}


class AssumptionCascadeArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "AssumptionCascadeArchitect"

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
        critical_assumptions: list[dict] = []
        for a in assumptions:
            sensitivity = str(a.get("sensitivity", "MEDIUM")).upper()
            if sensitivity in ["CRITICAL", "HIGH"]:
                critical_assumptions.append(a)

        def _domain(assumption_text: str) -> str:
            t = assumption_text.lower()
            # Price-point cues before "compet*" so "competitive at 999" maps to pricing
            if any(w in t for w in ["price", "cost", "₹", "plan", "tier", "free", "999"]):
                return "pricing"
            if any(w in t for w in ["onboard", "setup", "first", "start", "ux"]):
                return "onboarding"
            if any(w in t for w in ["trust", "review", "brand", "credib"]):
                return "trust"
            if any(w in t for w in ["retain", "churn", "return", "habit"]):
                return "retention"
            if any(w in t for w in ["compet", "alternative", "market leader", "free product"]):
                return "competitive"
            if any(w in t for w in ["timing", "season", "market", "launch"]):
                return "timing"
            if any(w in t for w in ["distribut", "offline", "available", "channel"]):
                return "distribution"
            if any(w in t for w in ["perform", "speed", "battery", "accura"]):
                return "performance"
            return "general"

        domain_impact_weights = {
            "pricing": 0.30, "retention": 0.20, "trust": 0.18,
            "onboarding": 0.15, "competitive": 0.12, "timing": 0.10,
            "distribution": 0.08, "performance": 0.07, "general": 0.05,
        }

        confidence_mult_map = {
            "VALIDATED_EXTERNAL": 1.0,
            "VALIDATED_INTERNAL": 0.75,
            "DESIGN_INTENT":      0.55,
            "ASPIRATIONAL":       0.40,
        }

        assumption_deltas: list[dict] = []
        for a in critical_assumptions:
            raw = str(a.get("text", a.get("assumption", "")))
            domain = _domain(raw)
            claim_conf = str(a.get("claim_confidence", "DESIGN_INTENT"))
            confidence_mult = confidence_mult_map.get(claim_conf, 0.55)
            pessimistic_delta = domain_impact_weights.get(domain, 0.05) * (1 - confidence_mult)
            assumption_deltas.append({
                "assumption_text":  raw[:80],
                "domain":           domain,
                "delta":            round(pessimistic_delta, 4),
                "claim_confidence": claim_conf,
            })

        assumption_deltas.sort(key=lambda x: x["delta"], reverse=True)
        primary_failure = (
            assumption_deltas[0]
            if assumption_deltas else
            {"domain": "none", "delta": 0.0}
        )

        compound_prob = 0.0
        if len(assumption_deltas) >= 2:
            d1 = assumption_deltas[0]["domain"]
            d2 = assumption_deltas[1]["domain"]
            corr_key = tuple(sorted([d1, d2]))
            correlation = ASSUMPTION_CORRELATION_MAP.get(corr_key, 0.30)
            p_a = assumption_deltas[0]["delta"]
            p_b = assumption_deltas[1]["delta"]
            compound_prob = min(0.95, p_a * p_b * (1 + correlation))

        validated_count = sum(
            1 for a in assumption_deltas
            if a["claim_confidence"] in ["VALIDATED_EXTERNAL", "VALIDATED_INTERNAL"]
        )
        viral = float(agent_profile.get("viral_coefficient", 0) or 0)
        positive_cascade = validated_count >= 3 and viral > 0.25

        blind_spots = [
            a for a in assumption_deltas
            if a["claim_confidence"] in ["ASPIRATIONAL", "DESIGN_INTENT"] and a["delta"] > 0.08
        ]
        blind_spot_score = min(1.0, len(blind_spots) * 0.25)

        cluster_sensitivity = (
            "HIGH" if any(x in cluster.cluster_id for x in ["student", "tier3", "tier2_price"]) else
            "MEDIUM"
        )

        total_delta = sum(a["delta"] for a in assumption_deltas[:3])
        cascade_risk = min(0.95, total_delta + compound_prob * 0.5)

        severity = (
            "CRITICAL" if cascade_risk > 0.40 or compound_prob > 0.30 else
            "WARNING"  if cascade_risk > 0.20 or len(blind_spots) >= 2 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "primary_failure_domain_delta": float(primary_failure.get("delta", 0.0)),
                "compound_failure_probability": round(compound_prob, 4),
                "positive_cascade_active":      1.0 if positive_cascade else 0.0,
                "blind_spot_score":             round(blind_spot_score, 4),
                "total_cascade_risk":           round(cascade_risk, 4),
                "critical_assumption_count":    float(len(critical_assumptions)),
                "validated_assumption_count":   float(validated_count),
            },
            flags={
                "dual_failure_risk":        compound_prob > 0.30,
                "blind_spot_detected":      len(blind_spots) >= 2,
                "positive_cascade":         positive_cascade,
                "existential_risk":         cascade_risk > 0.50,
                "cluster_sensitivity_high": cluster_sensitivity == "HIGH",
            },
            narrative_findings=[
                (
                    f"Primary failure domain: {primary_failure.get('domain', 'none')} "
                    f"(Δ{primary_failure.get('delta', 0):.2f})"
                ),
                (
                    f"Compound failure prob: {compound_prob * 100:.1f}% | "
                    f"Blind spots: {len(blind_spots)}"
                ),
                f"Cascade risk: {cascade_risk:.2f} | Positive cascade: {positive_cascade}",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        existential = [o for o in outputs if o.flags.get("existential_risk")]
        blind_spot  = [o for o in outputs if o.flags.get("blind_spot_detected")]
        affected    = list({o.cluster_id for o in existential + blind_spot})
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(existential)} clusters at existential risk; "
                f"{len(blind_spot)} with founder blind spots"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(existential) * 0.05, 3),
            conversion_impact=round(len(existential) * 0.08, 3),
            recommended_action="Validate critical assumptions with real users before launch",
            severity="CRITICAL" if existential else "WARNING" if blind_spot else "INFO",
        )
