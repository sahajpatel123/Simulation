"""
HealthSafetyHardwareArchitect — clinical validation, doctor dependency, health privacy, and compliance.

health_hardware product type only.
Includes ARRIVE→BROWSE and BROWSE→CONSIDER transition overrides gated by clinical validation.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class HealthSafetyHardwareArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "HealthSafetyHardwareArchitect"

    @property
    def product_types(self) -> list[str]:
        return ["health_hardware"]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t         = cluster.base_traits
        risk_av   = t["risk_aversion"]
        trust     = t["trust"]
        motivation = t["motivation"]
        literacy  = t["digital_literacy"]
        patience  = t["patience_score"]
        income    = t["income_level"]
        age       = cluster.demographic_profile.get("age_bracket", "25-35")
        family_ori = (
            0.7 if any(x in cluster.cluster_id for x in [
                "family", "parent", "couple", "health_conscious"
            ]) else 0.3
        )

        # ── Extract signals from assumptions ──────────────────────────────
        clinical_validation = False
        doctor_partnership  = False
        has_certifications  = False
        use_case = "wellness"
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in [
                "clinical", "fda", "cdsco", "validated",
                "peer reviewed", "study",
            ]):
                clinical_validation = True
            if any(w in text for w in ["doctor", "physician", "hospital", "clinic"]):
                doctor_partnership = True
            if any(w in text for w in ["bis", "iso", "ce mark", "approved", "certified"]):
                has_certifications = True
            if any(w in text for w in ["chronic", "diabetes", "blood pressure", "glucose", "cardiac"]):
                use_case = "chronic"
            elif any(w in text for w in ["fitness", "wellness", "steps", "sleep", "activity"]):
                use_case = "wellness"

        # ── Clinical requirement ──────────────────────────────────────────
        clin_req = (
            0.95 if use_case == "chronic" else
            0.80 if use_case == "diagnostic" else
            0.45 if use_case == "wellness" else
            0.20
        )
        clin_req *= (
            1.4 if any(x in age for x in ["50", "55", "60"]) else
            0.5 if any(x in age for x in ["18", "22", "25"]) else
            1.0
        )
        clin_req = min(0.98, clin_req * (1 + risk_av * 0.3))
        clinical_met = clinical_validation

        # ── Doctor dependency ─────────────────────────────────────────────
        doctor_dep = min(0.90,
            clin_req * (1.6 if any(x in age for x in ["45", "50", "55", "60"]) else 0.5)
        )
        doctor_dep *= (1 if doctor_partnership else 0.6)

        # ── Other metrics ─────────────────────────────────────────────────
        family_driver = min(0.80,
            family_ori * 0.4 * (
                1.8
                if use_case == "chronic" and any(x in age for x in ["18", "22", "25", "28"])
                else 1.0
            )
        )

        chronic_frac = 0.70 if use_case == "chronic" else 0.20

        health_privacy = min(0.90,
            (1 - trust) * 1.4 * (
                1.8 if use_case == "chronic" else
                1.4 if use_case == "diagnostic" else
                0.9
            )
        )
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if "cloud" in text and "third party" in text:
                health_privacy = min(0.98, health_privacy * 2.0)

        insurance_expect = min(0.70,
            (1 - income) * 0.3 * (1.6 if use_case == "chronic" else 0.5)
        )

        reg_trust = 0.0
        if has_certifications:
            reg_trust = 0.18
            reg_trust += 0.20 if doctor_partnership else 0.0
        reg_trust = min(0.40, reg_trust)

        habit_strength   = float(agent_profile.get("day30_survival", 0.20))
        usage_compliance = min(0.85,
            motivation * 0.6 + habit_strength * 0.3 * (
                0.95 if use_case == "chronic" else 0.5
            )
        )

        alert_fatigue = min(0.80,
            (1 - patience) * 0.4 * (
                1.3 if any(x in age for x in ["18", "22", "25"]) else 0.8
            )
        )

        health_records_int = min(0.60,
            literacy * 0.3
            + (
                0.2 if any(x in cluster.cluster_id for x in ["enthusiast", "professional"]) else 0.0
            )
        )

        # ── Clinical gate — blocks entire funnel if unvalidated ───────────
        clinical_gate = 0.05 if (clin_req > 0.60 and not clinical_met) else 1.0

        severity = (
            "CRITICAL" if clinical_gate < 0.10 else
            "WARNING"  if health_privacy > 0.70 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "clinical_validation_requirement":        round(clin_req, 4),
                "clinical_validation_met":                1.0 if clinical_met else 0.0,
                "clinical_gate_multiplier":               round(clinical_gate, 4),
                "doctor_recommendation_dependency":       round(doctor_dep, 4),
                "family_vs_self_purchase_driver":         round(family_driver, 4),
                "chronic_vs_wellness_fraction":           round(chronic_frac, 4),
                "health_data_privacy_concern":            round(health_privacy, 4),
                "insurance_reimbursement_expectation":    round(insurance_expect, 4),
                "regulatory_approval_trust_effect":       round(reg_trust, 4),
                "usage_compliance_probability":           round(usage_compliance, 4),
                "alert_fatigue_risk":                     round(alert_fatigue, 4),
                "health_records_integration_expectation": round(health_records_int, 4),
            },
            flags={
                "clinical_validation_missing": clinical_gate < 0.10,
                "health_privacy_critical":     health_privacy > 0.70,
                "doctor_partnership_required": doctor_dep > 0.70,
                "alert_fatigue_risk_high":     alert_fatigue > 0.50,
            },
            narrative_findings=[
                f"Clinical req: {clin_req:.2f} | Met: {clinical_met} | Gate: {clinical_gate:.2f}",
                f"Health privacy concern: {health_privacy:.2f} | Doctor dep: {doctor_dep:.2f}",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        gate    = output.metrics.get("clinical_gate_multiplier", 1.0)
        privacy = output.metrics.get("health_data_privacy_concern", 0.3)
        return {
            ("ARRIVE", "BROWSE"):   max(0.05, min(0.95, gate)),
            ("BROWSE", "CONSIDER"): max(0.05, min(0.95, (1 - privacy * 0.6) * gate)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        no_clinical = [o for o in outputs if o.flags.get("clinical_validation_missing")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(no_clinical)} clusters blocked: clinical validation missing",
            affected_cluster_ids=[o.cluster_id for o in no_clinical],
            population_fraction=round(len(no_clinical) * 0.04, 3),
            conversion_impact=round(len(no_clinical) * 0.08, 3),
            recommended_action="Obtain clinical validation or CDSCO/BIS certification",
            severity="CRITICAL" if no_clinical else "INFO",
        )
