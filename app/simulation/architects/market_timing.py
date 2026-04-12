"""
MarketTimingArchitect — sets market receptivity baseline for each cluster.

Runs FIRST in the Conductor stack. All downstream architects modify on top
of these outputs. No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class MarketTimingArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "MarketTimingArchitect"

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
        literacy   = t["digital_literacy"]
        motivation = t["motivation"]
        income     = t["income_level"]
        risk_av    = t["risk_aversion"]
        age        = cluster.demographic_profile.get("age_bracket", "25-35")
        geo        = cluster.demographic_profile.get("geography", "metro")

        market_maturity = float(env_params.get("market_maturity", 0.5))
        scenario        = str(env_params.get("scenario_type", "NORMAL"))
        product_type    = str(env_params.get("product_type", "saas"))

        # ── Extract signals from assumptions ──────────────────────────────
        urgency_stated   = 0.5
        switching_stated = 0.5
        regulatory_dep   = False
        seasonal         = False

        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["urgent", "critical", "must have", "acute", "pain"]):
                urgency_stated = 0.80
            elif any(w in text for w in ["nice to have", "optional", "when time permits"]):
                urgency_stated = 0.25
            if any(w in text for w in ["switching", "migrate", "replace", "move from"]):
                switching_stated = 0.70
            if any(w in text for w in ["regulation", "compliance", "rbi", "sebi", "fda", "approval"]):
                regulatory_dep = True
            if any(w in text for w in ["festival", "diwali", "seasonal", "exam", "summer"]):
                seasonal = True

        # ── Category awareness ────────────────────────────────────────────
        awareness = market_maturity * (0.6 + literacy * 0.4)
        awareness = max(0.05, min(1.0, awareness))

        # ── Problem urgency ───────────────────────────────────────────────
        cluster_urgency_mult = (
            1.3 if any(x in cluster.cluster_id for x in ["founder", "professional", "startup"]) else
            0.6 if any(x in cluster.cluster_id for x in ["passive", "late_majority", "minimalist"]) else
            1.0
        )
        urgency = min(1.0, urgency_stated * cluster_urgency_mult)

        # ── Switching cost ────────────────────────────────────────────────
        sophistication = literacy * 0.6 + (1 - risk_av) * 0.4
        switching_cost = min(0.95, switching_stated * (
            1.4 if sophistication > 0.6 and market_maturity > 0.5 else 0.9
        ))

        # ── Budget cycle alignment ────────────────────────────────────────
        if any(x in cluster.cluster_id for x in ["enterprise", "b2b", "decision_maker"]):
            budget_alignment = 0.80 if scenario in ["HIGH_GROWTH"] else 0.50
        else:
            budget_alignment = 0.70

        # ── Technology adoption position ──────────────────────────────────
        if literacy > 0.7 and motivation > 0.7 and risk_av < 0.3:
            adoption_pos   = "early_adopter"
            adoption_score = 0.90
        elif literacy > 0.4 and risk_av < 0.7:
            adoption_pos   = "pragmatist"
            adoption_score = 0.60
        elif literacy < 0.3 or risk_av > 0.8:
            adoption_pos   = "laggard"
            adoption_score = 0.10
        else:
            adoption_pos   = "late_majority"
            adoption_score = 0.35

        # ── Derived metrics ───────────────────────────────────────────────
        trigger_sensitivity = (
            0.85 if any(x in cluster.cluster_id for x in ["founder", "startup", "professional"]) else
            0.30
        )

        category_creation_cost = (
            0.85 if awareness < 0.40 else
            0.50 if awareness < 0.75 else
            0.20
        )

        seasonal_coeff = 1.35 if seasonal else 1.0
        pricing_power  = min(1.20, market_maturity * 1.15 * (1.0 if urgency > 0.6 else 0.85))
        reg_risk       = 0.70 if regulatory_dep else 0.10
        reg_suppressor = 0.40 if regulatory_dep else 1.0

        severity = (
            "CRITICAL" if awareness < 0.30 or (regulatory_dep and urgency < 0.5) else
            "WARNING"  if awareness < 0.55 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "category_awareness_score":      round(awareness, 4),
                "problem_urgency_intensity":     round(urgency, 4),
                "switching_cost_depth":          round(switching_cost, 4),
                "budget_cycle_alignment":        round(budget_alignment, 4),
                "technology_adoption_score":     round(adoption_score, 4),
                "trigger_event_sensitivity":     round(trigger_sensitivity, 4),
                "category_creation_cost":        round(category_creation_cost, 4),
                "seasonal_demand_coefficient":   round(seasonal_coeff, 4),
                "market_maturity_pricing_power": round(pricing_power, 4),
                "regulatory_dependency_risk":    round(reg_risk, 4),
                "regulatory_suppressor":         round(reg_suppressor, 4),
            },
            flags={
                "awareness_critical":  awareness < 0.30,
                "regulatory_blocked":  regulatory_dep,
                "laggard_cluster":     adoption_pos == "laggard",
                "high_education_cost": category_creation_cost > 0.70,
                "adoption_position":   adoption_pos == "early_adopter",
            },
            narrative_findings=[
                f"Category awareness: {awareness * 100:.1f}% | Urgency: {urgency * 100:.1f}%",
                f"Adoption position: {adoption_pos} | Switching cost: {switching_cost:.2f}",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        awareness = output.metrics.get("category_awareness_score", 0.6)
        urgency   = output.metrics.get("problem_urgency_intensity", 0.5)
        reg       = output.metrics.get("regulatory_suppressor", 1.0)
        cat_cost  = output.metrics.get("category_creation_cost", 0.5)
        budget    = output.metrics.get("budget_cycle_alignment", 0.7)
        return {
            ("ARRIVE",  "BROWSE"):   max(0.05, min(0.95, awareness * urgency * reg)),
            ("BROWSE",  "CONSIDER"): max(0.05, min(0.95, (1 - cat_cost) * budget)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("awareness_critical")]
        blocked  = [o for o in outputs if o.flags.get("regulatory_blocked")]
        affected = list({o.cluster_id for o in critical + blocked})
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters have critical category awareness; "
                f"{len(blocked)} blocked by regulation"
            ),
            affected_cluster_ids=affected,
            population_fraction=round((len(critical) + len(blocked)) * 0.05, 3),
            conversion_impact=round((len(critical) + len(blocked)) * 0.04, 3),
            recommended_action="Invest in category education, check regulatory pathway",
            severity="CRITICAL" if (critical or blocked) else "INFO",
        )
