"""
PhysicalSensoryArchitect — build quality, materials, packaging, and tactile expectations.

Feeds downstream architects (e.g., retention, trust) — no transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class PhysicalSensoryArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "PhysicalSensoryArchitect"

    @property
    def product_types(self) -> list[str]:
        return ["consumer_hardware", "health_hardware", "iot_hardware", "wearable"]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t        = cluster.base_traits
        income   = t["income_level"]
        social   = t["social_orientation"]
        risk_av  = t["risk_aversion"]
        patience = t["patience_score"]
        age      = cluster.demographic_profile.get("age_bracket", "25-35")
        AOV      = float(env_params.get("average_order_value", 3000))
        product_type = str(env_params.get("product_type", "consumer_hardware"))
        gift_prob    = float(agent_profile.get("gift_purchase_probability", 0.1))

        # ── Build quality expectation ─────────────────────────────────────
        if   AOV > 5000: expected_tier = "premium"
        elif AOV > 1500: expected_tier = "mid"
        else:            expected_tier = "budget"

        qual_sensitivity = income * (1.3 if expected_tier == "premium" else 1.0)
        qual_sensitivity = min(1.0, qual_sensitivity)

        # ── Material preferences ──────────────────────────────────────────
        material_metal       = min(0.90, income * 0.75)
        material_plastic     = max(0.10, 0.70 - income * 0.4)
        material_sustainable = min(0.60,
            (0.3 if any(x in age for x in ["18", "22", "25", "28"]) else 0.1)
            + (0.2 if income > 0.5 else 0.0)
        )

        packaging_weight = (
            gift_prob * 0.4
            + income * 0.3
            + (0.25 if float(agent_profile.get("brand_deficit_multiplier", 0.8)) < 0.65 else 0.0)
        )
        packaging_weight = min(0.90, packaging_weight)

        # ── Form factor tolerance ─────────────────────────────────────────
        weight_tolerance = (
            0.3 if product_type == "wearable" else
            0.7 if product_type == "iot_hardware" else
            0.5
        )

        review_write_likelihood = social * 0.3 * (
            2.5 if "enthusiast" in cluster.cluster_id else 0.4
        )
        first_touch_review = min(0.80, review_write_likelihood)

        repairability = min(0.70,
            (1 - income) * 0.4
            + (0.2 if any(x in age for x in ["40", "45", "50", "55"]) else 0.0)
            + (0.15 if AOV > 8000 else 0.0)
        )

        tactile_exp = min(0.80,
            income * 0.4 + (0.3 if product_type == "wearable" else 0.1)
        )

        severity = (
            "WARNING" if income > 0.6 and AOV < 2000 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "build_quality_sensitivity":      round(qual_sensitivity, 4),
                "material_pref_metal":            round(material_metal, 4),
                "material_pref_plastic":          round(material_plastic, 4),
                "material_pref_sustainable":      round(material_sustainable, 4),
                "packaging_quality_weight":       round(packaging_weight, 4),
                "weight_form_factor_tolerance":   round(weight_tolerance, 4),
                "first_touch_review_probability": round(first_touch_review, 4),
                "repairability_sentiment":        round(repairability, 4),
                "tactile_feedback_expectation":   round(tactile_exp, 4),
            },
            flags={
                "premium_expectation_mismatch": income > 0.6 and AOV < 2000,
                "packaging_critical":           packaging_weight > 0.60,
                "sustainability_matters":       material_sustainable > 0.35,
                "high_review_risk":             first_touch_review > 0.50,
            },
            narrative_findings=[
                f"Material: metal pref {material_metal:.2f}, packaging weight {packaging_weight:.2f}",
                f"Review probability on first touch: {first_touch_review * 100:.1f}%",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        mismatch = [o for o in outputs if o.flags.get("premium_expectation_mismatch")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(mismatch)} clusters have premium expectations vs budget price",
            affected_cluster_ids=[o.cluster_id for o in mismatch],
            population_fraction=round(len(mismatch) * 0.04, 3),
            conversion_impact=round(len(mismatch) * 0.03, 3),
            recommended_action="Upgrade materials or reposition pricing tier",
            severity="WARNING" if mismatch else "INFO",
        )
