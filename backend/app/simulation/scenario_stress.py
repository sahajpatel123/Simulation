from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ScenarioImpact:
    scenario_key: str
    scenario_name: str
    description: str
    projected_conversion_rate: float
    conversion_delta_pct: float
    vulnerability_score: float  # 0.0 (resilient) to 1.0 (highly vulnerable)
    risk_level: str  # LOW, MODERATE, HIGH, SEVERE
    impact_summary: str
    mitigation_recommendation: str


@dataclass
class ScenarioStressResult:
    simulation_id: int
    base_conversion_rate: float
    overall_resilience_score: float  # 0 to 100
    most_vulnerable_scenario: str
    most_resilient_scenario: str
    scenario_impacts: list[ScenarioImpact]


class ScenarioStressAnalyzer:
    """
    Evaluates multi-cluster simulation resilience against 4 macroeconomic & market stress presets:
      1. RECESSION: Purchasing power contraction + heightened price sensitivity.
      2. PRICE_WAR: Incumbent price slashing + Trust deficit for new entrants.
      3. VIRAL_CATALYST: High social propagation + lower onboarding friction.
      4. CHANNEL_BOTTLENECK: Digital/offline channel blockage & distribution drop.
    """

    def analyze(
        self,
        simulation_id: int,
        base_conversion_rate: float,
        cluster_breakdown: dict[str, float],
        cluster_registry: list[dict[str, Any]],
        domain_findings: list[dict[str, Any]] | None = None,
        product_type: str = "saas",
    ) -> ScenarioStressResult:
        base_rate = max(0.0001, float(base_conversion_rate))
        domain_findings = domain_findings or []

        cluster_weights = {
            c["cluster_id"]: float(c.get("population_weight", 0.02))
            for c in cluster_registry
        }

        # 1. Recession Scenario
        recession_rate = self._compute_recession_rate(cluster_breakdown, cluster_weights)
        recession_impact = self._build_recession_impact(base_rate, recession_rate, product_type)

        # 2. Price War Scenario
        price_war_rate = self._compute_price_war_rate(cluster_breakdown, cluster_weights, domain_findings)
        price_war_impact = self._build_price_war_impact(base_rate, price_war_rate)

        # 3. Viral Catalyst Scenario
        viral_rate = self._compute_viral_rate(cluster_breakdown, cluster_weights)
        viral_impact = self._build_viral_impact(base_rate, viral_rate)

        # 4. Channel Bottleneck Scenario
        channel_rate = self._compute_channel_rate(cluster_breakdown, cluster_weights)
        channel_impact = self._build_channel_impact(base_rate, channel_rate)

        impacts = [recession_impact, price_war_impact, viral_impact, channel_impact]

        # Calculate overall resilience score (0 - 100)
        negative_deltas = [imp.conversion_delta_pct for imp in impacts if imp.scenario_key != "VIRAL_CATALYST"]
        avg_negative_drop = sum(abs(d) for d in negative_deltas) / max(1, len(negative_deltas))
        resilience_score = round(max(0.0, min(100.0, 100.0 - avg_negative_drop * 0.8)), 1)

        worst_scenario = min(impacts, key=lambda x: x.conversion_delta_pct).scenario_name
        best_scenario = max(impacts, key=lambda x: x.conversion_delta_pct).scenario_name

        return ScenarioStressResult(
            simulation_id=simulation_id,
            base_conversion_rate=round(base_rate, 4),
            overall_resilience_score=resilience_score,
            most_vulnerable_scenario=worst_scenario,
            most_resilient_scenario=best_scenario,
            scenario_impacts=impacts,
        )

    def _compute_recession_rate(
        self,
        cluster_breakdown: dict[str, float],
        cluster_weights: dict[str, float],
    ) -> float:
        weighted_rate = 0.0
        for cid, rate in cluster_breakdown.items():
            w = cluster_weights.get(cid, 0.02)
            is_budget = any(term in cid.lower() for term in ["student", "tier3", "budget", "freelancer"])
            decay = 0.45 if is_budget else 0.80
            weighted_rate += rate * decay * w
        return weighted_rate

    def _compute_price_war_rate(
        self,
        cluster_breakdown: dict[str, float],
        cluster_weights: dict[str, float],
        domain_findings: list[dict[str, Any]],
    ) -> float:
        pricing_failed = any(f.get("domain") == "Pricing" for f in domain_findings)
        decay_factor = 0.55 if pricing_failed else 0.72

        weighted_rate = 0.0
        for cid, rate in cluster_breakdown.items():
            w = cluster_weights.get(cid, 0.02)
            weighted_rate += rate * decay_factor * w
        return weighted_rate

    def _compute_viral_rate(
        self,
        cluster_breakdown: dict[str, float],
        cluster_weights: dict[str, float],
    ) -> float:
        weighted_rate = 0.0
        for cid, rate in cluster_breakdown.items():
            w = cluster_weights.get(cid, 0.02)
            is_social = any(term in cid.lower() for term in ["genz", "metro", "student", "creator", "digital"])
            boost = 1.60 if is_social else 1.15
            weighted_rate += rate * boost * w
        return min(0.95, weighted_rate)

    def _compute_channel_rate(
        self,
        cluster_breakdown: dict[str, float],
        cluster_weights: dict[str, float],
    ) -> float:
        weighted_rate = 0.0
        for cid, rate in cluster_breakdown.items():
            w = cluster_weights.get(cid, 0.02)
            is_remote = any(term in cid.lower() for term in ["tier3", "rural", "offline", "traditional"])
            decay = 0.30 if is_remote else 0.90
            weighted_rate += rate * decay * w
        return weighted_rate

    def _build_recession_impact(
        self, base_rate: float, recession_rate: float, product_type: str
    ) -> ScenarioImpact:
        delta_pct = round(((recession_rate - base_rate) / base_rate) * 100, 1)
        vuln = round(max(0.0, min(1.0, abs(delta_pct) / 60.0)), 2)
        risk = self._risk_level(vuln)
        return ScenarioImpact(
            scenario_key="RECESSION",
            scenario_name="Macroeconomic Recession",
            description="30% drop in disposable income and heightened consumer risk aversion across all segments.",
            projected_conversion_rate=round(recession_rate, 4),
            conversion_delta_pct=delta_pct,
            vulnerability_score=vuln,
            risk_level=risk,
            impact_summary=f"Conversion drops by {abs(delta_pct)}% under macroeconomic contraction.",
            mitigation_recommendation=(
                "Introduce flexible monthly billing or a low-friction starter tier to protect conversion."
                if product_type in ("saas", "mobile_app")
                else "Provide EMI financing and value-focused bundle guarantees."
            ),
        )

    def _build_price_war_impact(
        self, base_rate: float, price_war_rate: float
    ) -> ScenarioImpact:
        delta_pct = round(((price_war_rate - base_rate) / base_rate) * 100, 1)
        vuln = round(max(0.0, min(1.0, abs(delta_pct) / 60.0)), 2)
        risk = self._risk_level(vuln)
        return ScenarioImpact(
            scenario_key="PRICE_WAR",
            scenario_name="Aggressive Incumbent Price War",
            description="Established market incumbents slash pricing by 40% and increase switching barriers.",
            projected_conversion_rate=round(price_war_rate, 4),
            conversion_delta_pct=delta_pct,
            vulnerability_score=vuln,
            risk_level=risk,
            impact_summary=f"Incumbent price slashing causes a {abs(delta_pct)}% drop in customer acquisition.",
            mitigation_recommendation="Differentiate on unique feature speed and specialized workflow velocity rather than competing solely on price.",
        )

    def _build_viral_impact(
        self, base_rate: float, viral_rate: float
    ) -> ScenarioImpact:
        delta_pct = round(((viral_rate - base_rate) / base_rate) * 100, 1)
        vuln = 0.0
        return ScenarioImpact(
            scenario_key="VIRAL_CATALYST",
            scenario_name="Viral Adoption Catalyst",
            description="High organic word-of-mouth referral velocity and active social advocacy.",
            projected_conversion_rate=round(viral_rate, 4),
            conversion_delta_pct=delta_pct,
            vulnerability_score=vuln,
            risk_level="LOW",
            impact_summary=f"Viral mechanics boost conversion by +{delta_pct}%.",
            mitigation_recommendation="Implement in-app invite loops and social proof badges to capture maximum upside.",
        )

    def _build_channel_impact(
        self, base_rate: float, channel_rate: float
    ) -> ScenarioImpact:
        delta_pct = round(((channel_rate - base_rate) / base_rate) * 100, 1)
        vuln = round(max(0.0, min(1.0, abs(delta_pct) / 60.0)), 2)
        risk = self._risk_level(vuln)
        return ScenarioImpact(
            scenario_key="CHANNEL_BOTTLENECK",
            scenario_name="Distribution Channel Bottleneck",
            description="Disruption in primary acquisition channels or key regional distribution networks.",
            projected_conversion_rate=round(channel_rate, 4),
            conversion_delta_pct=delta_pct,
            vulnerability_score=vuln,
            risk_level=risk,
            impact_summary=f"Channel bottleneck causes a {abs(delta_pct)}% drop in target segment reach.",
            mitigation_recommendation="Diversify customer acquisition channels across organic search, direct partnerships, and referral networks.",
        )

    def _risk_level(self, vulnerability_score: float) -> str:
        if vulnerability_score >= 0.70:
            return "SEVERE"
        if vulnerability_score >= 0.45:
            return "HIGH"
        if vulnerability_score >= 0.25:
            return "MODERATE"
        return "LOW"

    def to_dict(self, result: ScenarioStressResult) -> dict[str, Any]:
        return {
            "simulation_id": result.simulation_id,
            "base_conversion_rate": result.base_conversion_rate,
            "overall_resilience_score": result.overall_resilience_score,
            "most_vulnerable_scenario": result.most_vulnerable_scenario,
            "most_resilient_scenario": result.most_resilient_scenario,
            "scenario_impacts": [
                {
                    "scenario_key": imp.scenario_key,
                    "scenario_name": imp.scenario_name,
                    "description": imp.description,
                    "projected_conversion_rate": imp.projected_conversion_rate,
                    "conversion_delta_pct": imp.conversion_delta_pct,
                    "vulnerability_score": imp.vulnerability_score,
                    "risk_level": imp.risk_level,
                    "impact_summary": imp.impact_summary,
                    "mitigation_recommendation": imp.mitigation_recommendation,
                }
                for imp in result.scenario_impacts
            ],
        }
