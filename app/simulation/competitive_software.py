from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Software category price benchmarks (INR/month) ──
SOFTWARE_PRICE_BENCHMARKS: dict[str, dict] = {
    "saas": {
        "freemium_ceiling": 0,
        "budget_ceiling": 299,
        "mid_range": 999,
        "premium_floor": 2999,
        "enterprise_floor": 9999,
        "market_leader_price": 1499,
    },
    "marketplace": {
        "freemium_ceiling": 0,
        "budget_ceiling": 199,
        "mid_range": 799,
        "premium_floor": 1999,
        "enterprise_floor": 4999,
        "market_leader_price": 999,
    },
    "mobile_app": {
        "freemium_ceiling": 0,
        "budget_ceiling": 99,
        "mid_range": 299,
        "premium_floor": 799,
        "enterprise_floor": 1999,
        "market_leader_price": 199,
    },
    "developer_tool": {
        "freemium_ceiling": 0,
        "budget_ceiling": 499,
        "mid_range": 1999,
        "premium_floor": 4999,
        "enterprise_floor": 19999,
        "market_leader_price": 2999,
    },
    "enterprise_software": {
        "freemium_ceiling": 0,
        "budget_ceiling": 2999,
        "mid_range": 9999,
        "premium_floor": 29999,
        "enterprise_floor": 99999,
        "market_leader_price": 19999,
    },
}

# ── Feature dimensions per software product type ──
SOFTWARE_FEATURE_DIMENSIONS: dict[str, list[str]] = {
    "saas": [
        "onboarding_quality",
        "feature_depth",
        "integration_ecosystem",
        "api_quality",
        "reporting_analytics",
        "collaboration",
        "mobile_experience",
        "customer_support",
    ],
    "marketplace": [
        "supply_liquidity",
        "demand_acquisition",
        "trust_safety",
        "payment_options",
        "search_discovery",
        "review_system",
        "logistics_support",
        "seller_tools",
    ],
    "mobile_app": [
        "onboarding_speed",
        "core_loop_clarity",
        "notification_quality",
        "offline_capability",
        "performance",
        "ui_polish",
        "social_features",
        "monetisation_fairness",
    ],
    "developer_tool": [
        "documentation_quality",
        "sdk_completeness",
        "api_reliability",
        "debugging_tooling",
        "community_size",
        "pricing_transparency",
        "open_source_friendliness",
        "ci_cd_integration",
    ],
    "enterprise_software": [
        "security_compliance",
        "sso_saml_support",
        "audit_logging",
        "role_permissions",
        "sla_uptime",
        "dedicated_support",
        "data_residency",
        "procurement_process",
    ],
}

# ── Competitor extraction from assumptions ──
COMPETITOR_SIGNALS = [
    "alternative to",
    "competitor",
    "like ",
    "similar to",
    "better than",
    "vs ",
    "against ",
    "replaces",
    "beats",
    "unlike ",
    "instead of",
    "competing with",
]


@dataclass
class ExtractedCompetitor:
    name: str
    mention_type: str  # DIRECT | IMPLIED | CATEGORY
    raw_claim: str  # original assumption text
    confidence: float  # 0-1


@dataclass
class ClusterCompetitiveSoftwareProfile:
    cluster_id: str
    cluster_name: str
    conversion_rate: float
    population_fraction: float
    switching_friction: float
    displacement_days: int
    price_sensitivity_to_undercut: float  # how much cheaper to win
    feature_gap_score: float
    whitespace: bool
    primary_competitor: str
    recommendation: str


@dataclass
class CompetitiveSoftwareReport:
    product_type: str
    aov: float
    price_position: str
    extracted_competitors: list[ExtractedCompetitor]
    feature_scores: dict[str, float]
    cluster_profiles: list[ClusterCompetitiveSoftwareProfile]
    whitespace_clusters: list[str]
    displacement_timeline: dict[str, int]
    overall_differentiation: float
    recommended_positioning: str
    top_threats: list[str]
    top_opportunities: list[str]
    price_vs_benchmark: dict

    def to_dict(self) -> dict:
        return {
            "product_type": self.product_type,
            "aov": self.aov,
            "price_position": self.price_position,
            "extracted_competitors": [
                {
                    "name": c.name,
                    "mention_type": c.mention_type,
                    "raw_claim": c.raw_claim,
                    "confidence": round(c.confidence, 4),
                }
                for c in self.extracted_competitors
            ],
            "feature_scores": {k: round(v, 4) for k, v in self.feature_scores.items()},
            "whitespace_clusters": self.whitespace_clusters,
            "displacement_timeline": self.displacement_timeline,
            "overall_differentiation": round(self.overall_differentiation, 4),
            "recommended_positioning": self.recommended_positioning,
            "top_threats": self.top_threats,
            "top_opportunities": self.top_opportunities,
            "price_vs_benchmark": self.price_vs_benchmark,
            "cluster_profiles": [
                {
                    "cluster_id": p.cluster_id,
                    "cluster_name": p.cluster_name,
                    "conversion_rate": round(p.conversion_rate, 4),
                    "population_fraction": round(p.population_fraction, 4),
                    "switching_friction": round(p.switching_friction, 4),
                    "displacement_days": p.displacement_days,
                    "price_undercut_needed": round(p.price_sensitivity_to_undercut, 4),
                    "feature_gap_score": round(p.feature_gap_score, 4),
                    "whitespace": p.whitespace,
                    "primary_competitor": p.primary_competitor,
                    "recommendation": p.recommendation,
                }
                for p in sorted(
                    self.cluster_profiles,
                    key=lambda x: x.conversion_rate,
                    reverse=True,
                )
            ],
        }


class CompetitiveSoftwareAnalyser:
    def _extract_competitors(
        self,
        assumptions: list[dict],
    ) -> list[ExtractedCompetitor]:
        """
        Extracts competitor names from assumption text.
        Looks for signal phrases and extracts the following word/phrase.
        """
        competitors: list[ExtractedCompetitor] = []
        seen: set[str] = set()

        for a in assumptions:
            original = str(a.get("assumption", a.get("text", "")))
            text = original.lower()

            for signal in COMPETITOR_SIGNALS:
                idx = text.find(signal)
                if idx == -1:
                    continue
                # Extract word after signal
                after = text[idx + len(signal) :].strip()
                words = after.split()
                if not words:
                    continue
                comp_name = words[0].strip(".,;:!?()").title()
                if len(comp_name) < 2 or comp_name.lower() in seen:
                    continue
                seen.add(comp_name.lower())

                mention_type = (
                    "DIRECT"
                    if any(s in signal for s in ["alternative to", "vs ", "beats", "against"])
                    else "IMPLIED"
                    if any(s in signal for s in ["like ", "similar to", "unlike "])
                    else "CATEGORY"
                )
                cc = str(a.get("claim_confidence", "DESIGN_INTENT"))
                validated = cc in ("VALIDATED_EXTERNAL", "VALIDATED_INTERNAL")
                claim_confidence = round((1.0 if validated else 0.0) * 0.8 + 0.2, 4)

                competitors.append(
                    ExtractedCompetitor(
                        name=comp_name,
                        mention_type=mention_type,
                        raw_claim=original[:100],
                        confidence=claim_confidence,
                    )
                )

        return competitors[:8]  # cap at 8 competitors

    def _price_position(self, aov: float, product_type: str) -> str:
        benchmarks = SOFTWARE_PRICE_BENCHMARKS.get(
            product_type, SOFTWARE_PRICE_BENCHMARKS["saas"]
        )
        if aov == 0:
            return "FREEMIUM"
        if aov <= benchmarks["budget_ceiling"]:
            return "BUDGET"
        if aov <= benchmarks["mid_range"]:
            return "MID"
        if aov <= benchmarks["premium_floor"]:
            return "PREMIUM"
        return "ENTERPRISE"

    def _feature_scores_from_conductor(
        self,
        conductor_result: Any,
        product_type: str,
    ) -> dict[str, float]:
        """
        Derives feature quality scores from architect outputs.
        Uses mean architect metric values as proxy for feature quality.
        """
        dimensions = SOFTWARE_FEATURE_DIMENSIONS.get(product_type, [])
        if not dimensions:
            return {}

        # Pull overall cluster accountability as feature proxy
        accountability = getattr(conductor_result, "architect_accountability", {}) or {}

        # Map architects to feature dimensions
        ARCH_TO_DIM: dict[str, list[str]] = {
            "OnboardingArchitect": ["onboarding_quality", "onboarding_speed"],
            "FeatureAdoptionArchitect": ["feature_depth", "core_loop_clarity"],
            "RetentionArchitect": ["notification_quality", "mobile_experience"],
            "TrustArchitect": ["trust_safety", "review_system"],
            "SupportFrictionArchitect": ["customer_support", "dedicated_support"],
            "ViralityArchitect": ["social_features", "supply_liquidity"],
            "CompetitiveDynamicsArchitect": ["integration_ecosystem", "api_quality"],
            "MarketTimingArchitect": ["demand_acquisition", "community_size"],
            "PricingArchitect": ["monetisation_fairness", "pricing_transparency"],
        }

        dim_scores: dict[str, float] = {d: 0.55 for d in dimensions}

        # High accountability = architect found many problems = lower feature score
        for arch_name, arch_score in accountability.items():
            dims_for_arch = ARCH_TO_DIM.get(arch_name, [])
            for dim in dims_for_arch:
                if dim in dim_scores:
                    # High accountability score → lower feature score
                    dim_scores[dim] = max(0.1, 0.80 - arch_score * 0.6)

        return {k: round(v, 4) for k, v in dim_scores.items()}

    def _cluster_competitive_profile(
        self,
        cluster_id: str,
        cluster_name: str,
        cluster_data: dict,
        aov: float,
        price_position: str,
        feature_scores: dict,
        competitors: list[ExtractedCompetitor],
        arch_outputs: dict,
    ) -> ClusterCompetitiveSoftwareProfile:
        _ = aov
        conversion = float(cluster_data.get("conversion_rate", 0.05))
        _pop_fraction = float(cluster_data.get("population_fraction", 0.02))

        # Switching friction from CompetitiveDynamics architect output
        comp_metrics = arch_outputs.get("CompetitiveDynamicsArchitect", {}).get("metrics", {})
        base_friction = float(comp_metrics.get("incumbent_switching_friction", 0.50))
        # Adjust by conversion — high conversion = effectively lower friction already
        adj_friction = max(0.05, base_friction * (1.0 - conversion * 0.3))

        # Displacement timeline
        displacement_d = max(7, int(adj_friction * 90 * (1.0 - conversion * 0.5)))

        # Price undercut needed — price-sensitive clusters need bigger discount
        pricing_metrics = arch_outputs.get("PricingArchitect", {}).get("metrics", {})
        price_sens = float(pricing_metrics.get("will_pay_probability", 0.5))
        undercut_needed = max(0.0, (1.0 - price_sens) * 0.5)

        # Feature gap
        avg_feature = sum(feature_scores.values()) / max(len(feature_scores), 1)
        feature_gap = max(0.0, 1.0 - avg_feature)

        # Whitespace: conversion > 15% and friction < 0.35 and no strong competitor signal
        has_competitor = len(competitors) > 0
        whitespace = conversion > 0.15 and adj_friction < 0.35 and not has_competitor

        # Primary competitor for this cluster
        primary_comp = competitors[0].name if competitors else "No identified competitor"

        # Recommendation
        if whitespace:
            rec = "Acquire now — no incumbent detected, cluster is receptive"
        elif conversion > 0.25 and adj_friction < 0.50:
            rec = "Strong acquisition target — moderate friction, good fit signal"
        elif adj_friction > 0.75:
            rec = f"Long displacement cycle vs {primary_comp} — needs deep integration advantage"
        elif price_position in ["BUDGET", "FREEMIUM"] and undercut_needed < 0.2:
            rec = "Price advantage sufficient — execute on distribution"
        elif feature_gap > 0.50:
            rec = f"Feature parity gap — build missing dimensions before targeting {primary_comp} users"
        else:
            rec = "Build social proof and case studies specific to this segment"

        return ClusterCompetitiveSoftwareProfile(
            cluster_id=cluster_id,
            cluster_name=cluster_name,
            conversion_rate=conversion,
            population_fraction=cluster_data.get("population_fraction", 0.02),
            switching_friction=round(adj_friction, 4),
            displacement_days=displacement_d,
            price_sensitivity_to_undercut=round(undercut_needed, 4),
            feature_gap_score=round(feature_gap, 4),
            whitespace=whitespace,
            primary_competitor=primary_comp,
            recommendation=rec,
        )

    def analyse(
        self,
        assumptions: list[dict],
        conductor_result: Any,
        product_type: str,
        aov: float = 999.0,
    ) -> CompetitiveSoftwareReport:
        pt_key = (product_type or "saas").lower().strip()
        if pt_key not in SOFTWARE_PRICE_BENCHMARKS:
            pt_key = "saas"

        benchmarks = SOFTWARE_PRICE_BENCHMARKS.get(
            pt_key, SOFTWARE_PRICE_BENCHMARKS["saas"]
        )
        price_position = self._price_position(aov, pt_key)
        competitors = self._extract_competitors(assumptions)
        feature_scores = self._feature_scores_from_conductor(conductor_result, pt_key)
        overall_diff = sum(feature_scores.values()) / max(len(feature_scores), 1)

        cluster_results = getattr(conductor_result, "cluster_breakdown", {}) or {}
        cluster_results_raw = (
            conductor_result.cluster_results if hasattr(conductor_result, "cluster_results") else {}
        )

        # ── Per-cluster profiles ──
        from app.simulation.clusters.registry import ClusterRegistry

        registry = ClusterRegistry()
        clusters = {c.cluster_id: c for c in registry.all_clusters()}
        cluster_profiles: list[ClusterCompetitiveSoftwareProfile] = []
        whitespace: list[str] = []
        displacement_map: dict[str, int] = {}

        for cid, cr_val in cluster_results.items():
            cluster_def = clusters.get(cid)
            cluster_name = cluster_def.name if cluster_def else cid
            pop_frac = cluster_def.population_weight if cluster_def else 0.02

            # Get architect outputs for this cluster
            arch_out_raw = cluster_results_raw.get(cid, {})
            arch_dicts: dict = {}
            if arch_out_raw:
                for name, out in arch_out_raw.items():
                    m = getattr(out, "metrics", {}) or {}
                    f = getattr(out, "flags", {}) or {}
                    arch_dicts[name] = {"metrics": m, "flags": f}

            if isinstance(cr_val, (int, float)):
                conv_f = float(cr_val)
            elif isinstance(cr_val, dict):
                conv_f = float(cr_val.get("conversion_rate", 0.05))
            else:
                conv_f = 0.05

            cdata = {
                "conversion_rate": conv_f,
                "population_fraction": pop_frac,
            }

            profile = self._cluster_competitive_profile(
                cluster_id=cid,
                cluster_name=cluster_name,
                cluster_data=cdata,
                aov=aov,
                price_position=price_position,
                feature_scores=feature_scores,
                competitors=competitors,
                arch_outputs=arch_dicts,
            )
            cluster_profiles.append(profile)
            displacement_map[cid] = profile.displacement_days
            if profile.whitespace:
                whitespace.append(cid)

        # ── Price vs benchmark ──
        price_vs_bench = {
            "target_price_inr": aov,
            "budget_ceiling": benchmarks["budget_ceiling"],
            "mid_range": benchmarks["mid_range"],
            "premium_floor": benchmarks["premium_floor"],
            "market_leader_price": benchmarks["market_leader_price"],
            "vs_market_leader_pct": round(
                (aov - benchmarks["market_leader_price"])
                / max(benchmarks["market_leader_price"], 1)
                * 100,
                1,
            ),
            "position": price_position,
        }

        # ── Threats and opportunities ──
        threats: list[str] = []
        opportunities: list[str] = []

        if competitors:
            direct = [c for c in competitors if c.mention_type == "DIRECT"]
            if direct:
                n = len(cluster_profiles)
                avg_f = sum(p.switching_friction for p in cluster_profiles) / max(n, 1)
                threats.append(
                    f"Direct competitor identified: {direct[0].name} — "
                    f"switching friction averages {avg_f:.2f}"
                )
        if price_position == "ENTERPRISE" and pt_key not in [
            "enterprise_software",
            "developer_tool",
        ]:
            threats.append(
                "Enterprise pricing for non-enterprise product — high friction for SMB and consumer clusters"
            )
        high_friction_count = sum(1 for p in cluster_profiles if p.switching_friction > 0.70)
        if high_friction_count > 5:
            threats.append(
                f"{high_friction_count} clusters have entrenched incumbents (friction > 0.70) — long displacement cycles"
            )
        if overall_diff < 0.45:
            threats.append("Low overall differentiation score — product risks commoditisation")
        if not competitors and price_position == "PREMIUM":
            threats.append("No competitor data in assumptions — analysis may be overconfident")

        if whitespace:
            opportunities.append(
                f"{len(whitespace)} whitespace clusters identified — no competitor owns them"
            )
        low_friction_high_cr = [p for p in cluster_profiles if p.switching_friction < 0.35 and p.conversion_rate > 0.15]
        if low_friction_high_cr:
            opportunities.append(
                f"{len(low_friction_high_cr)} clusters are immediately acquirable with low switching friction"
            )
        if price_position in ["BUDGET", "MID"] and overall_diff > 0.6:
            opportunities.append("Accessible price with strong feature scores — best value positioning available")
        b2b_high = [p for p in cluster_profiles if "b2b" in p.cluster_id or "enterprise" in p.cluster_id]
        b2b_high_cr = [p for p in b2b_high if p.conversion_rate > 0.20]
        if b2b_high_cr:
            opportunities.append(f"{len(b2b_high_cr)} B2B clusters show strong conversion — consider PLG motion")

        # ── Recommended positioning ──
        if len(whitespace) >= 6:
            positioning = "Category creator — own the whitespace segments before incumbents respond"
        elif price_position == "BUDGET" and overall_diff > 0.55:
            positioning = "Value leader — communicate feature quality to counter budget perception"
        elif price_position in ["MID", "PREMIUM"] and overall_diff > 0.65:
            positioning = "Quality premium — lead with depth and support quality vs incumbent breadth"
        elif competitors and (
            direct_mentions := [c for c in competitors if c.mention_type == "DIRECT"]
        ):
            positioning = (
                f"Head-to-head displacement of {direct_mentions[0].name} — "
                "target their lowest-friction clusters first"
            )
        elif price_position == "ENTERPRISE":
            positioning = "Enterprise land-and-expand — close one design partner, use as proof for next"
        else:
            positioning = "Differentiation play — identify one dimension no incumbent owns and build around it"

        return CompetitiveSoftwareReport(
            product_type=pt_key,
            aov=aov,
            price_position=price_position,
            extracted_competitors=competitors,
            feature_scores=feature_scores,
            cluster_profiles=cluster_profiles,
            whitespace_clusters=whitespace,
            displacement_timeline=displacement_map,
            overall_differentiation=round(overall_diff, 4),
            recommended_positioning=positioning,
            top_threats=threats[:4],
            top_opportunities=opportunities[:4],
            price_vs_benchmark=price_vs_bench,
        )