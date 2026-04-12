"""
MacroeconomicArchitect — scenario, calendar, FX, and subsidy correction multipliers.

Runs LAST in the Conductor stack as a correction layer. No transition overrides.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class MacroeconomicArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "MacroeconomicArchitect"

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
        t            = cluster.base_traits
        income       = t["income_level"]
        geo          = cluster.demographic_profile.get("geography", "metro")
        scenario     = str(env_params.get("scenario_type", "NORMAL"))
        product_type = str(env_params.get("product_type", "saas"))
        calendar     = str(env_params.get("calendar_period", "NORMAL"))

        # ── Extract from assumptions ──────────────────────────────────────
        usd_pricing  = False
        gov_eligible = False
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if any(w in text for w in ["usd", "dollar", "$", "foreign currency"]):
                usd_pricing = True
            if any(w in text for w in [
                "government scheme", "subsidy", "pm scheme", "digital india", "startup india",
            ]):
                gov_eligible = True

        # ── RECESSION / HIGH_GROWTH ───────────────────────────────────────
        if scenario == "RECESSION":
            price_ceil_mult = (
                0.58 if income < 0.3 else
                0.74 if income < 0.6 else
                0.88
            )
            freemium_mult   = 0.62
            annual_mult     = 0.50
            emi_mult        = 1.30
            b2b_mult        = 0.55
            upgrade_mult    = 1.55
        elif scenario == "HIGH_GROWTH":
            price_ceil_mult = 1.20
            freemium_mult   = 1.10
            annual_mult     = 1.35
            emi_mult        = 0.90
            b2b_mult        = 1.40
            upgrade_mult    = 0.80
        else:
            price_ceil_mult = 1.0
            freemium_mult   = 1.0
            annual_mult     = 1.0
            emi_mult        = 1.0
            b2b_mult        = 1.0
            upgrade_mult    = 1.0

        # ── FESTIVAL SEASON ───────────────────────────────────────────────
        festival_mult = 1.0
        if calendar == "FESTIVAL_SEASON":
            festival_mult = (
                1.38 if product_type in ["consumer_hardware", "wearable"] else
                1.25 if product_type == "health_hardware" else
                1.18 if product_type == "saas" else
                1.05
            )
        elif calendar == "NEW_YEAR":
            festival_mult = (
                1.32 if product_type == "health_hardware" else
                1.22 if product_type == "saas" else
                1.0
            )
        elif calendar == "FISCAL_YEAR_END":
            festival_mult = 1.40 if product_type in ["enterprise_software", "b2b_hardware"] else 1.0
        elif calendar == "POST_EXAM":
            festival_mult = 0.72 if any(x in cluster.cluster_id for x in ["student", "college"]) else 1.0

        # ── USD PRICING PENALTY ───────────────────────────────────────────
        usd_penalty = 1.0
        if usd_pricing:
            usd_penalty = (
                0.42 if income < 0.3 else
                0.73 if income < 0.6 else
                0.91
            )

        # ── GOVERNMENT SUBSIDY ────────────────────────────────────────────
        subsidy_mult = 1.0
        if gov_eligible:
            subsidy_mult = (
                1.45 if income < 0.3 else
                1.38 if geo == "tier3" else
                1.10
            )

        # ── COMPOSE FINAL CORRECTION BUNDLE ───────────────────────────────
        conversion_correction = (
            price_ceil_mult * festival_mult * usd_penalty * subsidy_mult
            * (b2b_mult if any(x in cluster.cluster_id for x in ["enterprise", "b2b", "smb"]) else 1.0)
        )
        conversion_correction = max(0.10, min(2.0, conversion_correction))

        severity = (
            "CRITICAL" if scenario == "RECESSION" and income < 0.3 else
            "WARNING"  if scenario == "RECESSION" or usd_pricing else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "price_ceiling_multiplier":      round(price_ceil_mult, 4),
                "freemium_conversion_mult":      round(freemium_mult, 4),
                "annual_payment_mult":             round(annual_mult, 4),
                "emi_attractiveness_mult":         round(emi_mult, 4),
                "b2b_procurement_mult":          round(b2b_mult, 4),
                "upgrade_cycle_mult":            round(upgrade_mult, 4),
                "festival_amplifier":            round(festival_mult, 4),
                "usd_pricing_penalty":           round(usd_penalty, 4),
                "government_subsidy_mult":       round(subsidy_mult, 4),
                "overall_conversion_correction": round(conversion_correction, 4),
            },
            flags={
                "recession_active":   scenario == "RECESSION",
                "festival_peak":      festival_mult > 1.20,
                "usd_penalty_severe": usd_penalty < 0.50,
                "subsidy_active":     gov_eligible,
            },
            narrative_findings=[
                f"Scenario: {scenario} | Conversion correction: {conversion_correction:.2f}x",
                f"Festival: {festival_mult:.2f}x | USD penalty: {usd_penalty:.2f}x",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        recession_hit = [
            o for o in outputs
            if o.flags.get("recession_active") and o.metrics["price_ceiling_multiplier"] < 0.70
        ]
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(recession_hit)} clusters under recession price-ceiling compression"
                if recession_hit else
                "Macro conditions within normal range for sampled clusters"
            ),
            affected_cluster_ids=[o.cluster_id for o in recession_hit],
            population_fraction=round(len(recession_hit) * 0.05, 3),
            conversion_impact=round(len(recession_hit) * 0.04, 3),
            recommended_action="Adjust pricing and billing for macro conditions",
            severity="WARNING" if recession_hit else "INFO",
        )
