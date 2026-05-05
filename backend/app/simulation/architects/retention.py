"""
RetentionArchitect — models day-1/7/30/90 survival and habit formation.

Consumes feature_depth_score and onboarding_completion_rate from
upstream architect outputs (passed via agent_profile by the Conductor).
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class RetentionArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "RetentionArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "saas", "marketplace", "mobile_app",
            "developer_tool", "enterprise_software",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        motivation = t["motivation"]
        patience   = t["patience_score"]
        trust      = t["trust"]
        price_sens = t["price_sensitivity"]
        income     = t["income_level"]
        loyalty    = 0.5  # default; refined by calibration in later steps

        # ── Upstream outputs from Conductor ──────────────────────────────
        feature_depth       = agent_profile.get("feature_depth_score", 0.4)
        onboard_completion  = agent_profile.get("onboarding_completion_rate", 0.65)

        # ── Use-frequency proxy from assumptions ─────────────────────────
        use_freq = "daily"
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            if "weekly" in text:
                use_freq = "weekly"
            elif "monthly" in text or "as needed" in text:
                use_freq = "as_needed"

        freq_mult = {"daily": 1.2, "weekly": 1.0, "as_needed": 0.75}[use_freq]

        # ── Survival curve ───────────────────────────────────────────────
        day1  = min(0.95, onboard_completion * (1.15 if feature_depth > 0.4 else 0.85))
        day7  = min(0.90, day1  * 0.65 * (1.3 if feature_depth > 0.5 else 0.7) * freq_mult)
        day30 = min(0.85, day7  * 0.55 * (1.25 if feature_depth > 0.45 else 0.80))
        day90 = min(0.80, day30 * 0.55 * (1 - price_sens * 0.15))

        # ── Habit formation ──────────────────────────────────────────────
        habit_base = (21 - motivation * 10) * (0.75 if feature_depth > 0.5 else 1.5)
        habit_days = max(7.0, habit_base)
        habit_days *= {"daily": 0.7, "weekly": 1.0, "as_needed": 1.8}[use_freq]

        churn_trigger = max(1, int(patience * 3 * (0.7 if trust < 0.4 else 1.0)))

        # ── Re-engagement + notification sensitivity ─────────────────────
        age = cluster.demographic_profile.get("age_bracket", "25-35")
        notif_rate  = min(0.60, motivation * 0.5 * trust * (0.2 if trust < 0.4 else 1.0))
        streak_resp = min(0.50, motivation * 0.4 * (1.5 if "18" in age or "22" in age else 0.6))
        pause_pref  = min(0.80, loyalty * 0.5 * (0.5 if income < 0.3 else 1.0))
        reeng_30    = min(0.40, motivation * 0.25 * trust)
        reeng_90    = min(0.20, reeng_30 * 0.45)

        session_pattern = (
            "deep_work" if motivation > 0.6 and patience > 0.6
            else "quick_check"
        )

        severity = (
            "CRITICAL" if day7 < 0.20 else
            "WARNING"  if day7 < 0.35 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "day1_survival":                  round(day1, 4),
                "day7_survival":                  round(day7, 4),
                "day30_survival":                 round(day30, 4),
                "day90_survival":                 round(day90, 4),
                "habit_loop_formation_days":      round(habit_days, 1),
                "churn_trigger_threshold":        float(churn_trigger),
                "notification_reengagement_rate": round(notif_rate, 4),
                "streak_gamification_response":   round(streak_resp, 4),
                "pause_vs_cancel_preference":     round(pause_pref, 4),
                "reengagement_probability_30d":   round(reeng_30, 4),
                "reengagement_probability_90d":   round(reeng_90, 4),
                "session_depth_score":            1.0 if session_pattern == "deep_work" else 0.3,
            },
            flags={
                "retention_critical":    day7 < 0.20,
                "habit_unlikely":        habit_days > 45,
                "session_pattern_deep":  session_pattern == "deep_work",
                "reengagement_possible": reeng_30 > 0.15,
            },
            narrative_findings=[
                f"Day-7 survival: {day7 * 100:.1f}% | Day-30: {day30 * 100:.1f}%",
                f"Habit loop forms in ~{habit_days:.0f} days ({use_freq} use)",
                f"Session pattern: {session_pattern}",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        day7 = output.metrics.get("day7_survival", 0.35)
        return {
            ("PURCHASE", "RETURN"): max(0.05, min(0.90, day7)),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("retention_critical")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(critical)} clusters have critical day-7 retention",
            affected_cluster_ids=[o.cluster_id for o in critical],
            population_fraction=round(len(critical) * 0.05, 3),
            conversion_impact=round(len(critical) * 0.03, 3),
            recommended_action="Improve time-to-value, add habit triggers, deepen feature adoption",
            severity="CRITICAL" if critical else "INFO",
        )
