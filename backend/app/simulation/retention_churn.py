from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RETENTION_DAYS = [1, 7, 30, 90]


@dataclass
class ClusterRetentionProfile:
    cluster_id: str
    cluster_name: str
    population_weight: float
    day1_survival: float
    day7_survival: float
    day30_survival: float
    day90_survival: float
    habit_loop_days: float
    churn_trigger: str
    reengagement_prob_30d: float
    reengagement_prob_90d: float
    session_pattern: str
    pause_vs_cancel_pref: float
    ltv_score: float


@dataclass
class RetentionChurnResult:
    generated_ui_id: int
    product_type: str
    market_day7_survival: float
    market_day30_survival: float
    market_day90_survival: float
    highest_churn_stage: str
    cluster_profiles: list[ClusterRetentionProfile]
    best_retention_cluster: str
    worst_retention_cluster: str
    reengagement_viable: bool
    churn_trigger_distribution: dict[str, int]


# Reference: architect metric keys that map to churn domains (documentation / future use)
CHURN_TRIGGER_MAP = {
    "price": ["price_hike_churn_at_20pct", "will_pay_probability"],
    "onboarding": ["onboarding_completion_rate", "empty_state_bounce_probability"],
    "feature": ["feature_depth_score", "feature_abandonment_rate"],
    "trust": ["brand_deficit_multiplier", "trust_decay_rate_per_incident"],
    "competition": ["incumbent_switching_friction", "competitive_displacement_days"],
    "support": ["support_ticket_likelihood", "bug_tolerance_threshold"],
    "habit": ["habit_loop_formation_days", "notification_reengagement_rate"],
}


class RetentionChurnEngine:

    def _get_retention_metrics(self, arch: dict) -> dict:
        return arch.get("RetentionArchitect", {}).get("metrics", {})

    def _get_pricing_metrics(self, arch: dict) -> dict:
        return arch.get("PricingArchitect", {}).get("metrics", {})

    def _get_onboarding_metrics(self, arch: dict) -> dict:
        return arch.get("OnboardingArchitect", {}).get("metrics", {})

    def _infer_churn_trigger(
        self,
        retention_m: dict,
        pricing_m: dict,
        onboarding_m: dict,
    ) -> str:
        """
        Identify primary churn driver from architect metrics.
        Returns the domain most likely causing churn.
        """
        scores: dict[str, float] = {}

        will_pay = float(pricing_m.get("will_pay_probability", 0.5))
        scores["price"] = 1.0 - will_pay

        onboard_cr = float(onboarding_m.get("onboarding_completion_rate", 0.7))
        scores["onboarding"] = 1.0 - onboard_cr

        habit_days = float(retention_m.get("habit_loop_formation_days", 21))
        scores["habit"] = min(1.0, habit_days / 60.0)

        d7 = float(retention_m.get("day7_survival", 0.35))
        d30 = float(retention_m.get("day30_survival", 0.20))
        drop_rate = (d7 - d30) / max(d7, 0.01)
        scores["feature"] = min(1.0, drop_rate)

        return max(scores, key=scores.get)

    def _ltv_score(
        self,
        d90: float,
        annual_pref: float,
        reeng_30: float,
        price_ceiling: float,
        aov: float,
    ) -> float:
        ceiling_ratio = min(1.0, price_ceiling / max(aov * 3, 1))
        return round(
            d90 * 0.40
            + annual_pref * 0.25
            + reeng_30 * 0.15
            + ceiling_ratio * 0.20,
            4,
        )

    def generate(
        self,
        generated_ui_id: int,
        conductor_results: dict[str, Any],
        cluster_registry: list[dict],
        aov: float = 999.0,
        product_type: str = "saas",
    ) -> RetentionChurnResult:

        profiles: list[ClusterRetentionProfile] = []
        churn_trigger_dist: dict[str, int] = {}

        for cluster_info in cluster_registry:
            cid = cluster_info["cluster_id"]
            cname = cluster_info.get("name", cid)
            weight = float(cluster_info.get("population_weight", 0.02))
            arch = conductor_results.get(cid, {})

            rm = self._get_retention_metrics(arch)
            pm = self._get_pricing_metrics(arch)
            om = self._get_onboarding_metrics(arch)

            d1 = float(rm.get("day1_survival", 0.45))
            d7 = float(rm.get("day7_survival", 0.30))
            d30 = float(rm.get("day30_survival", 0.18))
            d90 = float(rm.get("day90_survival", 0.10))

            habit_days = float(rm.get("habit_loop_formation_days", 21.0))
            reeng_30 = float(rm.get("reengagement_probability_30d", 0.10))
            reeng_90 = float(rm.get("reengagement_probability_90d", 0.05))
            session_score = float(rm.get("session_depth_score", 0.5))
            pause_pref = float(rm.get("pause_vs_cancel_preference", 0.3))
            annual_pref = float(pm.get("annual_payment_probability", 0.2))
            ceiling = float(pm.get("price_ceiling", aov))

            session_pat = "deep_work" if session_score >= 0.7 else "quick_check"
            trigger = self._infer_churn_trigger(rm, pm, om)
            churn_trigger_dist[trigger] = churn_trigger_dist.get(trigger, 0) + 1

            ltv = self._ltv_score(d90, annual_pref, reeng_30, ceiling, aov)

            profiles.append(
                ClusterRetentionProfile(
                    cluster_id=cid,
                    cluster_name=cname,
                    population_weight=weight,
                    day1_survival=d1,
                    day7_survival=d7,
                    day30_survival=d30,
                    day90_survival=d90,
                    habit_loop_days=habit_days,
                    churn_trigger=trigger,
                    reengagement_prob_30d=reeng_30,
                    reengagement_prob_90d=reeng_90,
                    session_pattern=session_pat,
                    pause_vs_cancel_pref=pause_pref,
                    ltv_score=ltv,
                )
            )

        def weighted_avg(attr: str) -> float:
            return round(
                sum(getattr(p, attr) * p.population_weight for p in profiles),
                4,
            )

        mkt_d7 = weighted_avg("day7_survival")
        mkt_d30 = weighted_avg("day30_survival")
        mkt_d90 = weighted_avg("day90_survival")

        mkt_d1 = weighted_avg("day1_survival")
        drops = {
            "day1": 1.0 - mkt_d1,
            "day7": max(0.0, mkt_d1 - mkt_d7),
            "day30": max(0.0, mkt_d7 - mkt_d30),
            "day90": max(0.0, mkt_d30 - mkt_d90),
        }
        # ``weighted_avg`` returns 0.0 for an empty registry, so the
        # stage drops would be 1.0 / 0.0 / 0.0 / 0.0 — guard explicitly.
        if profiles:
            highest_churn_stage = max(drops, key=drops.get)
        else:
            highest_churn_stage = "day1"

        if profiles:
            best = max(profiles, key=lambda p: p.day30_survival).cluster_id
            worst = min(profiles, key=lambda p: p.day30_survival).cluster_id
        else:
            best = ""
            worst = ""
        reeng_viable = any(p.reengagement_prob_30d > 0.15 for p in profiles)

        return RetentionChurnResult(
            generated_ui_id=generated_ui_id,
            product_type=product_type,
            market_day7_survival=mkt_d7,
            market_day30_survival=mkt_d30,
            market_day90_survival=mkt_d90,
            highest_churn_stage=highest_churn_stage,
            cluster_profiles=profiles,
            best_retention_cluster=best,
            worst_retention_cluster=worst,
            reengagement_viable=reeng_viable,
            churn_trigger_distribution=churn_trigger_dist,
        )

    def to_dict(self, result: RetentionChurnResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "product_type": result.product_type,
            "market_day7_survival": result.market_day7_survival,
            "market_day30_survival": result.market_day30_survival,
            "market_day90_survival": result.market_day90_survival,
            "highest_churn_stage": result.highest_churn_stage,
            "best_retention_cluster": result.best_retention_cluster,
            "worst_retention_cluster": result.worst_retention_cluster,
            "reengagement_viable": result.reengagement_viable,
            "churn_trigger_distribution": result.churn_trigger_distribution,
            "cluster_profiles": [
                {
                    "cluster_id": p.cluster_id,
                    "cluster_name": p.cluster_name,
                    "population_weight": p.population_weight,
                    "day1_survival": p.day1_survival,
                    "day7_survival": p.day7_survival,
                    "day30_survival": p.day30_survival,
                    "day90_survival": p.day90_survival,
                    "habit_loop_days": p.habit_loop_days,
                    "churn_trigger": p.churn_trigger,
                    "reengagement_30d": p.reengagement_prob_30d,
                    "reengagement_90d": p.reengagement_prob_90d,
                    "session_pattern": p.session_pattern,
                    "pause_vs_cancel_pref": p.pause_vs_cancel_pref,
                    "ltv_score": p.ltv_score,
                }
                for p in sorted(result.cluster_profiles, key=lambda x: -x.ltv_score)
            ],
        }
