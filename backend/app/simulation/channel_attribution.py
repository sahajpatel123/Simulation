from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CHANNELS = [
    "organic_search",
    "paid_search",
    "social_organic",
    "social_paid",
    "influencer",
    "word_of_mouth",
    "content_marketing",
    "email",
    "community",
    "offline_retail",
    "press_mention",
    "referral_program",
]


@dataclass
class ClusterChannelProfile:
    cluster_id: str
    cluster_name: str
    population_weight: float
    channel_scores: dict[str, float]
    primary_channel: str
    secondary_channel: str
    cac_multiplier: float
    viral_coefficient: float
    wom_strength: float
    paid_receptivity: float
    influencer_dependency: float


@dataclass
class ChannelAttributionResult:
    generated_ui_id: int
    product_type: str
    cluster_profiles: list[ClusterChannelProfile]
    market_channel_ranking: list[tuple[str, float]]
    highest_roi_channel: str
    lowest_cac_channel: str
    viral_growth_possible: bool
    recommended_channel_mix: dict[str, float]


class ChannelAttributionEngine:

    def _virality(self, arch: dict) -> dict:
        return arch.get("ViralityArchitect", {}).get("metrics", {})

    def _trust(self, arch: dict) -> dict:
        return arch.get("TrustArchitect", {}).get("metrics", {})

    def _timing(self, arch: dict) -> dict:
        return arch.get("MarketTimingArchitect", {}).get("metrics", {})

    def _competitive(self, arch: dict) -> dict:
        return arch.get("CompetitiveDynamicsArchitect", {}).get("metrics", {})

    def _score_channels(
        self,
        cluster_id: str,
        vm: dict,
        tm: dict,
        timing_m: dict,
        comp_m: dict,
        profile: dict,
    ) -> dict[str, float]:
        _ = profile
        wom = float(vm.get("word_of_mouth_coefficient", 0.5))
        organic_t = float(vm.get("organic_referral_trigger_score", 0.1))
        invite_cr = float(vm.get("invite_completion_rate", 0.3))
        content_v = float(vm.get("content_virality_rate", 0.1))
        community = float(vm.get("community_building_participation", 0.2))
        press_lift = float(tm.get("press_mention_lift", 0.1))
        brand_def = float(tm.get("brand_deficit_multiplier", 0.8))
        free_trial = float(tm.get("free_trial_as_trust_substitute", 0.3))
        awareness = float(timing_m.get("category_awareness_score", 0.6))
        urgency = float(timing_m.get("problem_urgency_intensity", 0.5))
        switch_fr = float(comp_m.get("incumbent_switching_friction", 0.4))

        is_tier3 = "tier3" in cluster_id
        is_metro = "metro" in cluster_id or "professional" in cluster_id
        is_student = "student" in cluster_id or "college" in cluster_id
        is_b2b = any(x in cluster_id for x in ["enterprise", "smb", "b2b", "decision"])

        scores: dict[str, float] = {}

        scores["organic_search"] = min(1.0, awareness * 0.6 + urgency * 0.4) * (0.6 if is_tier3 else 1.0)
        scores["paid_search"] = min(1.0, urgency * 0.7 + (1 - brand_def) * 0.3) * (0.5 if is_tier3 else 1.0)
        scores["social_organic"] = min(1.0, content_v * 0.5 + wom * 0.3 + (0.3 if is_student else 0.1))
        scores["social_paid"] = min(1.0, (1 - brand_def) * 0.5 + urgency * 0.3) * (0.4 if is_b2b else 1.0)
        scores["influencer"] = min(1.0, (1 - brand_def) * 0.6 + (0.4 if is_student or is_tier3 else 0.1))
        scores["word_of_mouth"] = min(1.0, wom * 0.5 + organic_t * 0.3 + (0.2 if is_tier3 else 0.0))
        scores["content_marketing"] = min(1.0, awareness * 0.4 + content_v * 0.4 + (0.2 if is_metro else 0.0))
        scores["email"] = min(1.0, free_trial * 0.4 + brand_def * 0.4) * (0.3 if is_tier3 else 1.0)
        scores["community"] = min(1.0, community * 0.6 + wom * 0.4) * (1.3 if is_b2b else 0.8)
        scores["offline_retail"] = min(1.0, (0.8 if is_tier3 else 0.2) + (1 - switch_fr) * 0.2)
        scores["press_mention"] = min(1.0, press_lift * 3.0 + (0.3 if is_metro else 0.0))
        scores["referral_program"] = min(1.0, invite_cr * 0.5 + organic_t * 0.4)

        return {k: round(min(1.0, v), 4) for k, v in scores.items()}

    def _cac_multiplier(self, scores: dict, primary: str) -> float:
        paid_channels = {"paid_search": 1.8, "social_paid": 1.6, "influencer": 1.4}
        organic_channels = {
            "word_of_mouth": 0.3,
            "referral_program": 0.4,
            "community": 0.5,
            "organic_search": 0.7,
        }
        return round(paid_channels.get(primary, organic_channels.get(primary, 1.0)), 3)

    def generate(
        self,
        generated_ui_id: int,
        conductor_results: dict[str, Any],
        cluster_registry: list[dict],
        product_type: str = "saas",
    ) -> ChannelAttributionResult:
        profiles: list[ClusterChannelProfile] = []

        for cluster_info in cluster_registry:
            cid = cluster_info["cluster_id"]
            cname = cluster_info.get("name", cid)
            weight = float(cluster_info.get("population_weight", 0.02))
            arch = conductor_results.get(cid, {})

            vm = self._virality(arch)
            tm = self._trust(arch)
            timing_m = self._timing(arch)
            comp_m = self._competitive(arch)

            scores = self._score_channels(cid, vm, tm, timing_m, comp_m, {})
            sorted_ch = sorted(scores, key=scores.get, reverse=True)
            primary = sorted_ch[0]
            secondary = sorted_ch[1] if len(sorted_ch) > 1 else primary
            cac_mult = self._cac_multiplier(scores, primary)

            profiles.append(
                ClusterChannelProfile(
                    cluster_id=cid,
                    cluster_name=cname,
                    population_weight=weight,
                    channel_scores=scores,
                    primary_channel=primary,
                    secondary_channel=secondary,
                    cac_multiplier=cac_mult,
                    viral_coefficient=float(vm.get("viral_coefficient", 0.05)),
                    wom_strength=float(vm.get("word_of_mouth_coefficient", 0.5)),
                    paid_receptivity=float(scores.get("social_paid", 0.3)),
                    influencer_dependency=float(scores.get("influencer", 0.2)),
                )
            )

        channel_weighted: dict[str, float] = {ch: 0.0 for ch in CHANNELS}
        for p in profiles:
            for ch, score in p.channel_scores.items():
                channel_weighted[ch] += score * p.population_weight
        market_ranking = sorted(channel_weighted.items(), key=lambda x: -x[1])

        highest_roi = min(profiles, key=lambda p: p.cac_multiplier).primary_channel
        lowest_cac_ch = min(
            channel_weighted,
            key=lambda c: (
                1.8
                if c in {"paid_search", "social_paid"}
                else 0.4
                if c in {"word_of_mouth", "referral_program"}
                else 1.0
            )
            - channel_weighted[c] * 0.3,
        )

        viral_possible = any(p.viral_coefficient > 1.0 for p in profiles)

        top5 = market_ranking[:5]
        top5_total = sum(s for _, s in top5) or 1.0
        channel_mix = {ch: round(s / top5_total, 3) for ch, s in top5}

        return ChannelAttributionResult(
            generated_ui_id=generated_ui_id,
            product_type=product_type,
            cluster_profiles=profiles,
            market_channel_ranking=market_ranking,
            highest_roi_channel=highest_roi,
            lowest_cac_channel=lowest_cac_ch,
            viral_growth_possible=viral_possible,
            recommended_channel_mix=channel_mix,
        )

    def to_dict(self, result: ChannelAttributionResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "product_type": result.product_type,
            "highest_roi_channel": result.highest_roi_channel,
            "lowest_cac_channel": result.lowest_cac_channel,
            "viral_growth_possible": result.viral_growth_possible,
            "recommended_channel_mix": result.recommended_channel_mix,
            "market_channel_ranking": [
                {"channel": ch, "weighted_score": round(s, 4)} for ch, s in result.market_channel_ranking
            ],
            "cluster_profiles": [
                {
                    "cluster_id": p.cluster_id,
                    "cluster_name": p.cluster_name,
                    "population_weight": p.population_weight,
                    "primary_channel": p.primary_channel,
                    "secondary_channel": p.secondary_channel,
                    "cac_multiplier": p.cac_multiplier,
                    "viral_coefficient": p.viral_coefficient,
                    "wom_strength": p.wom_strength,
                    "paid_receptivity": p.paid_receptivity,
                    "influencer_dependency": p.influencer_dependency,
                    "channel_scores": p.channel_scores,
                }
                for p in sorted(result.cluster_profiles, key=lambda x: x.cac_multiplier)
            ],
        }
