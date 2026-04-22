from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

PRICE_POINTS_INR = [99, 199, 299, 499, 699, 999, 1499, 1999, 2999, 4999, 9999, 19999]


@dataclass
class ClusterPricingProfile:
    cluster_id: str
    cluster_name: str
    price_ceiling: float  # max willingness to pay (INR)
    optimal_price: float  # highest price with >50% conversion
    freemium_ceiling: float  # max freemium conversion rate
    emi_required: bool  # EMI needed to convert at AOV
    annual_preference: float  # probability of choosing annual plan
    price_curve: dict[int, float]  # price_point → predicted_conversion


@dataclass
class PricingSensitivityResult:
    generated_ui_id: int
    aov: float
    overall_elasticity: float  # how sensitive overall market is to price
    cluster_profiles: list[ClusterPricingProfile]
    market_segments: dict  # price band → clusters that convert
    recommended_price: float  # highest price where >30% of market converts
    revenue_optimal_price: float  # price × conversion maximised


class PricingSensitivityEngine:

    def _get_pricing_metrics(self, architect_outputs: dict) -> dict:
        return architect_outputs.get("PricingArchitect", {}).get("metrics", {})

    def _conversion_at_price(
        self,
        price: float,
        price_ceiling: float,
        will_pay_prob: float,
        emi_likelihood: float,
        aov: float,
    ) -> float:
        if price <= 0 or price_ceiling <= 0:
            return 0.0
        # Base: how much of ceiling this price represents
        ratio = price / price_ceiling
        if ratio > 1.20:
            return 0.0  # hard ceiling
        if ratio > 1.0:
            return round(will_pay_prob * 0.05, 4)  # slight overstretch
        # Linear decay with EMI boost for high prices
        base = will_pay_prob * max(0.0, 1.0 - ratio * 0.85)
        if price > aov * 0.8 and emi_likelihood > 0.3:
            base = min(0.95, base * (1 + emi_likelihood * 0.4))
        return round(max(0.0, min(0.95, base)), 4)

    def generate(
        self,
        generated_ui_id: int,
        conductor_results: dict[str, Any],  # cluster_id → arch output dicts
        cluster_registry: list[dict],  # [{cluster_id, name, population_weight}]
        aov: float = 999.0,
    ) -> PricingSensitivityResult:

        cluster_profiles: list[ClusterPricingProfile] = []
        # price band → list of (cluster_id, conversion_rate)
        market_segments: dict[int, list[tuple[str, float]]] = defaultdict(list)

        for cluster_info in cluster_registry:
            cid = cluster_info["cluster_id"]
            cname = cluster_info.get("name", cid)
            arch = conductor_results.get(cid, {})
            pm = self._get_pricing_metrics(arch)

            ceiling = float(pm.get("price_ceiling", aov * 1.2))
            will_pay = float(pm.get("will_pay_probability", 0.3))
            freemium_c = float(pm.get("freemium_conversion_ceiling", 0.04))
            emi_likely = float(pm.get("emi_adoption_likelihood", 0.0))
            annual_pref = float(pm.get("annual_payment_probability", 0.2))

            # Build price curve across standard price points
            curve: dict[int, float] = {}
            for pp in PRICE_POINTS_INR:
                curve[pp] = self._conversion_at_price(
                    float(pp), ceiling, will_pay, emi_likely, aov
                )
                market_segments[pp].append((cid, curve[pp]))

            # Optimal price: highest point where conversion > 0.5 of max
            max_conv = max(curve.values()) if curve else 0.0
            threshold = max_conv * 0.50
            optimal = max(
                (pp for pp, cv in curve.items() if cv >= threshold),
                default=aov,
            )

            cluster_profiles.append(
                ClusterPricingProfile(
                    cluster_id=cid,
                    cluster_name=cname,
                    price_ceiling=round(ceiling, 2),
                    optimal_price=float(optimal),
                    freemium_ceiling=freemium_c,
                    emi_required=emi_likely > 0.40,
                    annual_preference=annual_pref,
                    price_curve=curve,
                )
            )

        # Market-wide: which price point converts >30% of weighted market
        cluster_weights = {c["cluster_id"]: c.get("population_weight", 0.02) for c in cluster_registry}
        recommended_price = aov
        revenue_optimal = aov
        best_revenue = 0.0

        for pp in PRICE_POINTS_INR:
            segs = dict(market_segments[pp])
            weighted_conv = sum(
                segs.get(cid, 0.0) * cluster_weights.get(cid, 0.02) for cid in cluster_weights
            )
            if weighted_conv >= 0.30:
                recommended_price = float(pp)
            revenue = pp * weighted_conv
            if revenue > best_revenue:
                best_revenue = revenue
                revenue_optimal = float(pp)

        # Elasticity: variance of conversion across price points (higher = more sensitive)
        all_curves = [p.price_curve for p in cluster_profiles]
        if all_curves:
            mid_conv = sum(c.get(999, 0) for c in all_curves) / len(all_curves)
            high_conv = sum(c.get(4999, 0) for c in all_curves) / len(all_curves)
            elasticity = round(max(0.0, mid_conv - high_conv), 4)
        else:
            elasticity = 0.5

        return PricingSensitivityResult(
            generated_ui_id=generated_ui_id,
            aov=aov,
            overall_elasticity=elasticity,
            cluster_profiles=cluster_profiles,
            market_segments={
                pp: sorted(segs, key=lambda x: -x[1])[:5]  # top 5 clusters per price
                for pp, segs in market_segments.items()
            },
            recommended_price=recommended_price,
            revenue_optimal_price=revenue_optimal,
        )

    def to_dict(self, result: PricingSensitivityResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "aov": result.aov,
            "overall_elasticity": result.overall_elasticity,
            "recommended_price": result.recommended_price,
            "revenue_optimal_price": result.revenue_optimal_price,
            "cluster_profiles": [
                {
                    "cluster_id": p.cluster_id,
                    "cluster_name": p.cluster_name,
                    "price_ceiling": p.price_ceiling,
                    "optimal_price": p.optimal_price,
                    "freemium_ceiling": p.freemium_ceiling,
                    "emi_required": p.emi_required,
                    "annual_preference": p.annual_preference,
                    "price_curve": {str(k): v for k, v in p.price_curve.items()},
                }
                for p in sorted(result.cluster_profiles, key=lambda x: -x.price_ceiling)
            ],
            "market_segments": {
                str(pp): [{"cluster_id": cid, "conversion_rate": cr} for cid, cr in segs]
                for pp, segs in result.market_segments.items()
            },
        }
