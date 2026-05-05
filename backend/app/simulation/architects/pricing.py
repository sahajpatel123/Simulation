"""
PricingArchitect — evaluates whether a cluster will pay at the given AOV.

Computes 13 pricing-behavioural metrics from cluster traits and env_params.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class PricingArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "PricingArchitect"

    @property
    def product_types(self) -> list[str]:
        return self.ALL_PRODUCT_TYPES

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        income     = t["income_level"]
        price_sens = t["price_sensitivity"]
        motivation = t["motivation"]
        trust      = t["trust"]
        literacy   = t["digital_literacy"]
        AOV        = float(env_params.get("average_order_value", 999))

        # ── Core metrics ────────────────────────────────────────────────

        price_ceiling = income * (1 - price_sens) * AOV * 2.4 * trust

        freemium_ceiling = (
            (1 - price_sens) * 0.12
            * (0.3 if income < 0.2 else 0.6 if income < 0.5 else 1.0)
            * (1.4 if motivation > 0.8 else 0.5 if motivation < 0.4 else 1.0)
        )

        anchoring = 0.08 * (1.5 - literacy) * (trust if trust > 0.4 else 0.5)
        anchoring = max(0.01, min(0.20, anchoring))

        loyalty = t.get("loyalty_score", 0.5)
        annual_prob = income * 0.4 * trust * (1.3 if loyalty > 0.6 else 1.0)
        annual_prob = min(0.85, annual_prob)

        discount_response = price_sens * 0.6 * (1.3 if motivation > 0.7 else 1.0)

        churn_20 = max(0.0, price_sens * 0.30 - loyalty * 0.15)
        churn_40 = max(0.0, price_sens * 0.55 - loyalty * 0.15)
        churn_60 = max(0.0, price_sens * 0.80 - loyalty * 0.15)

        grandfathering   = loyalty * 0.5
        per_seat         = income * 0.6
        usage_anxiety    = price_sens * 0.5 * (
            1.5 if literacy < 0.4 else 0.7 if literacy > 0.7 else 1.0
        )
        refund_expect    = (1 - trust) * 0.4

        will_pay = price_ceiling / AOV if AOV > 0 else 0.5
        will_pay = max(0.05, min(0.95, will_pay))

        # ── Aggregation ─────────────────────────────────────────────────

        metrics = {
            "price_ceiling":               round(price_ceiling, 2),
            "freemium_conversion_ceiling": round(freemium_ceiling, 4),
            "anchoring_effect":            round(anchoring, 4),
            "annual_payment_probability":  round(annual_prob, 4),
            "discount_urgency_response":   round(discount_response, 4),
            "price_hike_churn_at_20pct":   round(churn_20, 4),
            "price_hike_churn_at_40pct":   round(churn_40, 4),
            "price_hike_churn_at_60pct":   round(churn_60, 4),
            "grandfathering_expectation":  round(grandfathering, 4),
            "per_seat_tolerance":          round(per_seat, 4),
            "usage_billing_anxiety":       round(usage_anxiety, 4),
            "refund_expectation":          round(refund_expect, 4),
            "will_pay_probability":        round(will_pay, 4),
        }

        flags = {
            "will_pay_at_current_aov":      price_ceiling > AOV,
            "annual_preferred_over_monthly": annual_prob > 0.4,
            "freemium_ceiling_risk":        freemium_ceiling < 0.05,
            "pricing_is_kill_shot":         price_ceiling < AOV * 0.3,
        }

        severity = (
            "CRITICAL" if price_ceiling < AOV * 0.3 else
            "WARNING"  if price_ceiling < AOV * 0.7 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics=metrics,
            flags=flags,
            narrative_findings=[
                f"Price ceiling ₹{price_ceiling:.0f} vs AOV ₹{AOV:.0f}",
                f"Freemium conversion ceiling: {freemium_ceiling * 100:.1f}%",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        will_pay  = output.metrics.get("will_pay_probability", 0.5)
        anchoring = output.metrics.get("anchoring_effect", 0.08)
        return {
            ("DECIDE",   "PURCHASE"): max(0.05, min(0.95, will_pay)),
            ("CONSIDER", "DECIDE"):   1.0 + anchoring,
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("pricing_is_kill_shot")]
        # Use actual cluster weights when available; approximate 0.06 otherwise
        kill_fraction = round(len(critical) * 0.06, 3)
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(critical)} clusters have pricing kill shot",
            affected_cluster_ids=[o.cluster_id for o in critical],
            population_fraction=kill_fraction,
            conversion_impact=round(len(critical) * 0.03, 3),
            recommended_action="Lower price or add EMI/freemium tier",
            severity="CRITICAL" if critical else "INFO",
        )
