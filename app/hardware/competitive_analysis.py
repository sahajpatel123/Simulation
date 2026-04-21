from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CATEGORY_PRICE_BENCHMARKS: dict[str, dict[str, float]] = {
    "consumer_hardware": {
        "budget_ceiling": 2000,
        "mid_range": 5000,
        "premium_floor": 10000,
        "market_leader_price": 7999,
    },
    "health_hardware": {
        "budget_ceiling": 3000,
        "mid_range": 8000,
        "premium_floor": 15000,
        "market_leader_price": 12999,
    },
    "wearable": {
        "budget_ceiling": 2500,
        "mid_range": 7000,
        "premium_floor": 20000,
        "market_leader_price": 15999,
    },
    "iot_hardware": {
        "budget_ceiling": 1500,
        "mid_range": 4000,
        "premium_floor": 8000,
        "market_leader_price": 5999,
    },
    "b2b_hardware": {
        "budget_ceiling": 5000,
        "mid_range": 20000,
        "premium_floor": 50000,
        "market_leader_price": 35000,
    },
}

FEATURE_DIMENSIONS: dict[str, list[str]] = {
    "consumer_hardware": [
        "build_quality",
        "battery_life",
        "connectivity",
        "display_quality",
        "audio_quality",
        "portability",
    ],
    "health_hardware": [
        "accuracy",
        "clinical_validation",
        "sensor_count",
        "data_privacy",
        "doctor_integration",
        "battery_life",
    ],
    "wearable": [
        "battery_life",
        "water_resistance",
        "sensor_accuracy",
        "ecosystem_compatibility",
        "design_aesthetics",
        "app_quality",
    ],
    "iot_hardware": [
        "protocol_support",
        "setup_ease",
        "reliability",
        "ecosystem_compatibility",
        "energy_efficiency",
        "range",
    ],
    "b2b_hardware": [
        "durability",
        "enterprise_support",
        "integration_ease",
        "security",
        "scalability",
        "compliance",
    ],
}

CLUSTER_SWITCHING_BASELINE: dict[str, float] = {
    "loyalist_returning_buyer": 0.85,
    "considered_hardware_researcher": 0.60,
    "health_hardware_skeptic": 0.80,
    "health_hardware_enthusiast": 0.45,
    "early_hardware_adopter_tech_enthusiast": 0.25,
    "value_hardware_buyer": 0.35,
    "gift_hardware_buyer": 0.30,
    "replacement_hardware_buyer": 0.55,
    "smart_home_early_adopter": 0.70,
    "anxiety_driven_researcher": 0.65,
    "impulsive_trend_follower": 0.15,
    "tier3_first_time_app_user": 0.20,
    "tier2_price_sensitive_pragmatist": 0.30,
    "urban_mid_income_hardware_considerer": 0.50,
    "wealthy_health_conscious_buyer": 0.55,
    "high_income_hardware_enthusiast": 0.40,
}


def _norm_category_key(raw: str | None) -> str:
    if not raw:
        return "consumer_hardware"
    k = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if k in CATEGORY_PRICE_BENCHMARKS:
        return k
    return "consumer_hardware"


@dataclass
class ClusterCompetitiveProfile:
    cluster_id: str
    cluster_name: str
    conversion_rate: float
    population_fraction: float
    price_position: str
    switching_friction: float
    displacement_days: int
    feature_gap_score: float
    whitespace: bool
    recommendation: str


@dataclass
class CompetitiveReport:
    category: str
    target_price_inr: float
    price_position: str
    price_vs_benchmark: dict[str, Any]
    feature_scores: dict[str, float]
    cluster_profiles: list[ClusterCompetitiveProfile]
    whitespace_clusters: list[str]
    displacement_timeline: dict[str, int]
    overall_differentiation: float
    recommended_positioning: str
    top_threats: list[str]
    top_opportunities: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "target_price_inr": self.target_price_inr,
            "price_position": self.price_position,
            "price_vs_benchmark": self.price_vs_benchmark,
            "feature_scores": {k: round(v, 4) for k, v in self.feature_scores.items()},
            "whitespace_clusters": self.whitespace_clusters,
            "displacement_timeline": self.displacement_timeline,
            "overall_differentiation": round(self.overall_differentiation, 4),
            "recommended_positioning": self.recommended_positioning,
            "top_threats": self.top_threats,
            "top_opportunities": self.top_opportunities,
            "cluster_profiles": [
                {
                    "cluster_id": p.cluster_id,
                    "cluster_name": p.cluster_name,
                    "conversion_rate": round(p.conversion_rate, 4),
                    "population_fraction": round(p.population_fraction, 4),
                    "price_position": p.price_position,
                    "switching_friction": round(p.switching_friction, 4),
                    "displacement_days": p.displacement_days,
                    "feature_gap_score": round(p.feature_gap_score, 4),
                    "whitespace": p.whitespace,
                    "recommendation": p.recommendation,
                }
                for p in sorted(
                    self.cluster_profiles,
                    key=lambda x: x.conversion_rate,
                    reverse=True,
                )
            ],
        }


class HardwareCompetitiveAnalyser:
    def _price_position(self, target_price: float, benchmarks: dict[str, float]) -> str:
        if target_price <= benchmarks["budget_ceiling"]:
            return "BUDGET"
        if target_price <= benchmarks["mid_range"]:
            return "MID"
        if target_price <= benchmarks["premium_floor"]:
            return "PREMIUM"
        return "OVERPRICED"

    def _feature_scores_from_spec(self, spec: dict, category: str) -> dict[str, float]:
        dimensions = FEATURE_DIMENSIONS.get(category, [])
        components = spec.get("components", [])
        if not isinstance(components, list):
            components = []
        scores: dict[str, float] = {}

        has_metal = any(
            "aluminium" in str(c.get("material", "")).lower()
            or "aluminum" in str(c.get("material", "")).lower()
            or "steel" in str(c.get("material", "")).lower()
            for c in components
        )
        has_silicone = any(
            "silicone" in str(c.get("material", "")).lower() for c in components
        )
        comp_count = len(components)
        avg_stress = sum(float(c.get("stress_rating", 0.5)) for c in components) / max(
            comp_count, 1
        )

        for dim in dimensions:
            if dim == "build_quality":
                scores[dim] = min(
                    1.0,
                    0.4 + (0.3 if has_metal else 0.0) + (0.2 if comp_count >= 4 else 0.1),
                )
            elif dim == "battery_life":
                has_battery = any("battery" in str(c.get("name", "")).lower() for c in components)
                scores[dim] = 0.70 if has_battery else 0.30
            elif dim == "water_resistance":
                scores[dim] = 0.80 if has_silicone else 0.35
            elif dim == "accuracy":
                sensor_count = sum(
                    1 for c in components if "sensor" in str(c.get("name", "")).lower()
                )
                scores[dim] = min(1.0, 0.3 + sensor_count * 0.2)
            elif dim == "clinical_validation":
                scores[dim] = 0.20
            elif dim == "ecosystem_compatibility":
                scores[dim] = 0.50
            elif dim == "setup_ease":
                scores[dim] = max(0.3, 1.0 - avg_stress * 0.5)
            elif dim == "durability":
                scores[dim] = min(
                    1.0,
                    0.3 + (0.4 if has_metal else 0.0) + (1.0 - avg_stress) * 0.3,
                )
            elif dim == "data_privacy":
                scores[dim] = 0.60
            else:
                scores[dim] = 0.55
        return scores

    def _cluster_competitive_profile(
        self,
        cluster_id: str,
        cluster_name: str,
        cluster_data: dict[str, Any],
        target_price: float,
        benchmarks: dict[str, float],
        feature_scores: dict[str, float],
        price_position: str,
    ) -> ClusterCompetitiveProfile:
        conversion = float(cluster_data.get("conversion_rate", 0.05))
        pop_fraction = float(cluster_data.get("population_fraction", 0.02))

        base_friction = CLUSTER_SWITCHING_BASELINE.get(cluster_id, 0.50)
        adj_friction = base_friction * (1.0 - conversion * 0.4)
        adj_friction = max(0.05, min(0.95, adj_friction))

        displacement_d = max(7, int(adj_friction * 120 * (1.0 - conversion * 0.5)))

        avg_feature = sum(feature_scores.values()) / max(len(feature_scores), 1)
        feature_gap = max(0.0, 1.0 - avg_feature)

        whitespace = conversion > 0.15 and adj_friction < 0.35

        if whitespace:
            rec = "Acquire aggressively — no incumbent owns this segment"
        elif conversion > 0.20 and adj_friction < 0.55:
            rec = "Strong opportunity — moderate friction, good fit"
        elif adj_friction > 0.70:
            rec = "Long displacement cycle — invest only if strategically critical"
        elif price_position == "OVERPRICED":
            rec = "Price barrier — consider EMI or lower-tier SKU for this segment"
        else:
            rec = "Build social proof and distribution before targeting"

        return ClusterCompetitiveProfile(
            cluster_id=cluster_id,
            cluster_name=cluster_name,
            conversion_rate=conversion,
            population_fraction=pop_fraction,
            price_position=price_position,
            switching_friction=round(adj_friction, 4),
            displacement_days=displacement_d,
            feature_gap_score=round(feature_gap, 4),
            whitespace=whitespace,
            recommendation=rec,
        )

    def analyse(
        self,
        spec: dict,
        cost_estimate: dict[str, Any],
        cluster_results: dict[str, Any],
    ) -> CompetitiveReport:
        category = _norm_category_key(str(spec.get("category", "consumer_hardware")))
        target_price = float(cost_estimate.get("target_price_inr", 1999))
        benchmarks = CATEGORY_PRICE_BENCHMARKS.get(
            category,
            CATEGORY_PRICE_BENCHMARKS["consumer_hardware"],
        )

        price_position = self._price_position(target_price, benchmarks)
        ml = benchmarks["market_leader_price"]
        price_vs_bench: dict[str, Any] = {
            "target_price_inr": target_price,
            "budget_ceiling": benchmarks["budget_ceiling"],
            "mid_range": benchmarks["mid_range"],
            "premium_floor": benchmarks["premium_floor"],
            "market_leader_price": ml,
            "vs_market_leader_pct": round(
                (target_price - ml) / max(ml, 1) * 100,
                1,
            ),
            "position": price_position,
        }

        feature_scores = self._feature_scores_from_spec(spec, category)
        overall_diff = sum(feature_scores.values()) / max(len(feature_scores), 1)

        cluster_profiles: list[ClusterCompetitiveProfile] = []
        whitespace: list[str] = []
        displacement_map: dict[str, int] = {}

        for cid, cdata in cluster_results.items():
            if not isinstance(cdata, dict):
                continue
            cname = str(cdata.get("cluster_name", cid))
            profile = self._cluster_competitive_profile(
                cluster_id=cid,
                cluster_name=cname,
                cluster_data=cdata,
                target_price=target_price,
                benchmarks=benchmarks,
                feature_scores=feature_scores,
                price_position=price_position,
            )
            cluster_profiles.append(profile)
            displacement_map[cid] = profile.displacement_days
            if profile.whitespace:
                whitespace.append(cid)

        tier_clusters = [
            p
            for p in cluster_profiles
            if any(x in p.cluster_id for x in ("tier2", "tier3"))
        ]
        tier3_coverage = sum(1 for p in tier_clusters if p.conversion_rate > 0.05) / max(
            len(tier_clusters), 1
        )

        threats: list[str] = []
        opportunities: list[str] = []

        if price_position == "OVERPRICED":
            threats.append(
                f"Price ₹{target_price:,.0f} is above premium floor — vulnerable to value competitors"
            )
        if price_position == "BUDGET" and overall_diff < 0.5:
            threats.append(
                "Budget positioning with low feature scores — race to bottom risk"
            )
        high_friction_clusters = [p for p in cluster_profiles if p.switching_friction > 0.70]
        if high_friction_clusters:
            threats.append(
                f"{len(high_friction_clusters)} clusters have strong incumbent lock-in (>0.70 friction)"
            )
        if (
            feature_scores.get("clinical_validation", 0.5) < 0.30
            and category == "health_hardware"
        ):
            threats.append(
                "No clinical validation — health_hardware_skeptic cluster blocked entirely"
            )
        if tier3_coverage < 0.30:
            threats.append(
                "Tier-2/Tier-3 distribution gap — 30%+ of market unreachable without offline channel"
            )

        if whitespace:
            opportunities.append(
                f"{len(whitespace)} whitespace clusters with no strong incumbent — acquire now"
            )
        if price_position == "MID" and overall_diff > 0.6:
            opportunities.append(
                "Mid-range price with strong features — premium-quality perception at accessible price"
            )
        low_friction_high_cr = [
            p
            for p in cluster_profiles
            if p.switching_friction < 0.35 and p.conversion_rate > 0.15
        ]
        if low_friction_high_cr:
            opportunities.append(
                f"{len(low_friction_high_cr)} clusters are immediately reachable with low friction"
            )
        if feature_scores.get("ecosystem_compatibility", 0.5) > 0.7:
            opportunities.append(
                "Strong ecosystem compatibility — smart_home_early_adopter segment accessible"
            )

        if price_position == "BUDGET" and overall_diff > 0.55:
            positioning = (
                "Position as 'best value in category' — undercut on price, match on features"
            )
        elif price_position in ("MID", "PREMIUM") and overall_diff > 0.65:
            positioning = (
                "Premium quality positioning — lead with build quality and feature depth"
            )
        elif len(whitespace) >= 5:
            positioning = (
                "Category creator — target underserved whitespace segments before incumbents react"
            )
        elif price_position == "OVERPRICED":
            positioning = (
                "Reposition: reduce price or launch lower-tier SKU to open addressable market"
            )
        else:
            positioning = (
                "Differentiation play — identify one feature dimension and own it completely"
            )

        return CompetitiveReport(
            category=category,
            target_price_inr=target_price,
            price_position=price_position,
            price_vs_benchmark=price_vs_bench,
            feature_scores=feature_scores,
            cluster_profiles=cluster_profiles,
            whitespace_clusters=whitespace,
            displacement_timeline=displacement_map,
            overall_differentiation=round(overall_diff, 4),
            recommended_positioning=positioning,
            top_threats=threats[:4],
            top_opportunities=opportunities[:4],
        )
