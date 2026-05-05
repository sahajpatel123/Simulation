"""
SetupFirstUseArchitect — out-of-box setup completion, guide format, and time-to-first-use.

Includes PURCHASE→RETURN transition override.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition
from app.core.utils import geo_tier


class SetupFirstUseArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "SetupFirstUseArchitect"

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
        patience     = t["patience_score"]
        trust        = t["trust"]
        motivation   = t["motivation"]
        age          = cluster.demographic_profile.get("age_bracket", "25-35")
        geo          = geo_tier(cluster.demographic_profile.get("geography", "metro"))
        product_type = str(env_params.get("product_type", "consumer_hardware"))

        # ── Extract signals from assumptions ──────────────────────────────
        complexity        = 0.5
        has_companion_app = False
        has_firmware      = False
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["app required", "companion app", "mobile app setup"]):
                has_companion_app = True
            if any(w in text for w in ["firmware", "update", "ota"]):
                has_firmware = True
            if any(w in text for w in ["complex", "multi-step", "assembly", "configuration"]):
                complexity = 0.80
            elif any(w in text for w in ["plug and play", "simple setup", "easy setup", "no app"]):
                complexity = 0.20

        # ── OOB completion rate ───────────────────────────────────────────
        base_completion = literacy * 0.5 + patience * 0.3 + motivation * 0.2
        if has_companion_app:
            base_completion *= 0.85
        if has_firmware:
            base_completion *= 0.75
        base_completion *= (
            0.65 if complexity > 0.6 else
            0.95 if complexity < 0.3 else
            0.85
        )
        if geo == "tier3":
            base_completion *= 0.50
        elif geo == "tier2":
            base_completion *= 0.82
        oob_completion = max(0.05, min(0.98, base_completion))

        # ── Derived metrics ───────────────────────────────────────────────
        app_install   = min(0.90, literacy * 0.7 * trust * (1.0 if has_companion_app else 0.4))
        account_aband = max(0.02, (1 - patience) * 0.25 * (1.4 if trust < 0.4 else 1.0))
        firmware_tol  = max(2, int(patience * 12 * (1.4 if motivation > 0.7 else 0.7)))
        assembly_tol  = max(1, int(patience * 0.7 * 5))
        pairing_tol   = max(1, int(literacy * 0.6 * 4 + (0.3 if geo == "metro" else 0.0)))

        if   literacy < 0.4:  guide_format = "printed"
        elif literacy < 0.7:  guide_format = "in_app"
        elif literacy > 0.8:  guide_format = "video"
        else:                 guide_format = "in_app"
        if any(x in age for x in ["50", "55", "60"]):
            guide_format = "printed"

        ttfmu = patience * 8 + motivation * 5
        ttfmu *= (0.75 if geo in ["tier3", "tier2"] else 1.0)
        ttfmu *= (0.80 if has_firmware else 1.0)
        ttfmu = max(3.0, min(20.0, ttfmu))

        customisation_depth = min(0.80,
            literacy * 0.4 + (0.3 if "enthusiast" in cluster.cluster_id else 0.0)
        )

        severity = (
            "CRITICAL" if oob_completion < 0.55 else
            "WARNING"  if oob_completion < 0.75 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "oob_setup_completion_rate":    round(oob_completion, 4),
                "companion_app_install_rate":   round(app_install, 4),
                "account_creation_abandonment": round(account_aband, 4),
                "firmware_update_tolerance_min": float(firmware_tol),
                "physical_assembly_tolerance":  float(assembly_tol),
                "pairing_friction_tolerance":   float(pairing_tol),
                "time_to_first_meaningful_use": round(ttfmu, 2),
                "initial_customisation_depth":  round(customisation_depth, 4),
            },
            flags={
                "setup_critical":   oob_completion < 0.55,
                "guide_printed":    guide_format == "printed",
                "tier3_setup_risk": geo == "tier3",
            },
            narrative_findings=[
                f"OOB completion: {oob_completion * 100:.1f}% | Guide: {guide_format}",
                f"Time to first use: {ttfmu:.1f} min | Firmware tolerance: {firmware_tol} min",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        completion = output.metrics.get("oob_setup_completion_rate", 0.80)
        return {
            ("PURCHASE", "RETURN"): max(0.05, min(0.95, 1.0 - (1.0 - completion) * 0.8)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("setup_critical")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(critical)} clusters have critical setup completion",
            affected_cluster_ids=[o.cluster_id for o in critical],
            population_fraction=round(len(critical) * 0.05, 3),
            conversion_impact=round(len(critical) * 0.06, 3),
            recommended_action="Simplify setup, add printed guide, reduce firmware update friction",
            severity="CRITICAL" if critical else "INFO",
        )
