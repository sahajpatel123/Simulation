"""
ClusterRegistry — all 52 TheCee consumer clusters.

Population weights sum to exactly 1.0.
Each cluster carries 8 canonical traits (matching cluster_parameters table).
sync_to_db() updates cluster_parameters.base_value on every app startup.

Performance contract:
    The registry is immutable after module load. ``all_clusters`` and
    ``clusters_for_product_type`` are memoised at the class level so repeated
    calls (a hot path during conductor runs) reuse a single list per
    product-type. ``_WEIGHT_SUM`` is computed once at import time.
"""
from __future__ import annotations

from threading import RLock
from typing import Any

from app.simulation.clusters.definitions import ClusterDefinition


# ---------------------------------------------------------------------------
# Helper: default variance block (reused across many clusters)
# ---------------------------------------------------------------------------

def _v(
    income: float = 0.07,
    digital: float = 0.07,
    motivation: float = 0.08,
    trust: float = 0.10,
    price: float = 0.07,
    risk: float = 0.08,
    patience: float = 0.08,
    social: float = 0.10,
) -> dict[str, float]:
    return {
        "income_level":       income,
        "digital_literacy":   digital,
        "motivation":         motivation,
        "trust":              trust,
        "price_sensitivity":  price,
        "risk_aversion":      risk,
        "patience_score":     patience,
        "social_orientation": social,
    }


def _t(
    income: float,
    digital: float,
    motivation: float,
    trust: float,
    price: float,
    risk: float,
    patience: float,
    social: float,
) -> dict[str, float]:
    return {
        "income_level":       income,
        "digital_literacy":   digital,
        "motivation":         motivation,
        "trust":              trust,
        "price_sensitivity":  price,
        "risk_aversion":      risk,
        "patience_score":     patience,
        "social_orientation": social,
    }


# ---------------------------------------------------------------------------
# All 52 cluster definitions
# Population weights are chosen to reflect realistic Indian consumer
# distribution and sum to exactly 1.00.
# ---------------------------------------------------------------------------

_CLUSTERS: dict[str, ClusterDefinition] = {

    # ── High-income metro professionals ──────────────────────────────────

    "metro_power_professional": ClusterDefinition(
        cluster_id="metro_power_professional",
        name="Metro power professional",
        description="Senior metro professional with high disposable income and strong digital fluency.",
        population_weight=0.06,
        base_traits=_t(0.82, 0.85, 0.80, 0.58, 0.18, 0.30, 0.70, 0.55),
        trait_variance=_v(0.05, 0.05, 0.08, 0.10, 0.05, 0.08, 0.08, 0.10),
        dominant_behavior_pattern="Converts on performance proof, pays annual",
        known_failure_modes=[
            "Feature depth too shallow → churns at day-30",
            "Performance claim unsubstantiated → rejects immediately",
        ],
        product_affinities=["saas", "developer_tool", "enterprise_software"],
        demographic_profile={"geography": "metro", "age_bracket": "28-42", "device_primary": "desktop"},
    ),

    "senior_enterprise_decision_maker": ClusterDefinition(
        cluster_id="senior_enterprise_decision_maker",
        name="Senior enterprise decision maker",
        description="C-suite or VP-level buyer with procurement authority and high risk aversion.",
        population_weight=0.03,
        base_traits=_t(0.90, 0.75, 0.65, 0.50, 0.10, 0.65, 0.55, 0.40),
        trait_variance=_v(0.04, 0.08, 0.10, 0.12, 0.04, 0.10, 0.10, 0.08),
        dominant_behavior_pattern="Requires vendor evaluation, committee sign-off, and security review",
        known_failure_modes=[
            "No enterprise security/compliance page → blocked in evaluation",
            "Self-serve only → cannot route to sales",
        ],
        product_affinities=["enterprise_software", "saas", "b2b_marketplace"],
        demographic_profile={"geography": "metro", "age_bracket": "38-55", "device_primary": "desktop"},
    ),

    "high_income_early_adopter": ClusterDefinition(
        cluster_id="high_income_early_adopter",
        name="High-income early adopter",
        description="Affluent tech enthusiast who actively seeks novel products and tolerates rough edges.",
        population_weight=0.04,
        base_traits=_t(0.80, 0.90, 0.88, 0.62, 0.15, 0.20, 0.80, 0.65),
        trait_variance=_v(0.06, 0.05, 0.07, 0.10, 0.05, 0.06, 0.07, 0.09),
        dominant_behavior_pattern="Buys on novelty and social signal, evangelises if delighted",
        known_failure_modes=[
            "Looks too mainstream → loses interest",
            "No beta/early-access framing → skips",
        ],
        product_affinities=["consumer_app", "consumer_hardware", "wearable", "iot_hardware", "developer_tool", "saas"],
        demographic_profile={"geography": "metro", "age_bracket": "25-38", "device_primary": "mobile"},
    ),

    "affluent_metro_late_majority": ClusterDefinition(
        cluster_id="affluent_metro_late_majority",
        name="Affluent metro late majority",
        description="High-income professional who waits for social proof before adopting.",
        population_weight=0.04,
        base_traits=_t(0.78, 0.72, 0.60, 0.55, 0.22, 0.55, 0.45, 0.60),
        trait_variance=_v(0.06, 0.08, 0.10, 0.10, 0.07, 0.09, 0.09, 0.09),
        dominant_behavior_pattern="Converts after seeing 10+ reviews and a trusted peer recommendation",
        known_failure_modes=[
            "Fewer than 50 public reviews → defers purchase",
            "No social proof → stays on consideration page",
        ],
        product_affinities=["consumer_app", "health_hardware", "saas"],
        demographic_profile={"geography": "metro", "age_bracket": "35-52", "device_primary": "mobile"},
    ),

    "high_income_hardware_enthusiast": ClusterDefinition(
        cluster_id="high_income_hardware_enthusiast",
        name="High-income hardware enthusiast",
        description="Well-off consumer who researches specs deeply and buys premium hardware.",
        population_weight=0.03,
        base_traits=_t(0.80, 0.88, 0.82, 0.60, 0.16, 0.25, 0.75, 0.50),
        trait_variance=_v(0.05, 0.05, 0.07, 0.10, 0.05, 0.07, 0.07, 0.09),
        dominant_behavior_pattern="Deep spec comparison, buys after 3-5 YouTube reviews",
        known_failure_modes=[
            "No benchmark data → defers",
            "Specs page missing → bounces",
        ],
        product_affinities=["consumer_hardware", "wearable", "iot_hardware", "smart_home", "health_hardware"],
        demographic_profile={"geography": "metro", "age_bracket": "26-42", "device_primary": "desktop"},
    ),

    "wealthy_health_conscious_buyer": ClusterDefinition(
        cluster_id="wealthy_health_conscious_buyer",
        name="Wealthy health-conscious buyer",
        description="High-income individual prioritising health outcomes, willing to pay for premium wellness products.",
        population_weight=0.03,
        base_traits=_t(0.82, 0.78, 0.85, 0.65, 0.14, 0.28, 0.68, 0.58),
        trait_variance=_v(0.05, 0.07, 0.07, 0.10, 0.05, 0.08, 0.08, 0.09),
        dominant_behavior_pattern="Converts on clinical/scientific credibility and premium packaging",
        known_failure_modes=[
            "No clinical evidence cited → skepticism blocks purchase",
            "Generic wellness claim → ignored",
        ],
        product_affinities=["health_hardware", "consumer_app", "d2c"],
        demographic_profile={"geography": "metro", "age_bracket": "30-50", "device_primary": "mobile"},
    ),

    # ── Urban mid-income professionals ───────────────────────────────────

    "urban_mid_income_saas_buyer": ClusterDefinition(
        cluster_id="urban_mid_income_saas_buyer",
        name="Urban mid-income SaaS buyer",
        description="Mid-income professional in a metro/tier-1 city evaluating SaaS tools for work.",
        population_weight=0.05,
        base_traits=_t(0.55, 0.75, 0.72, 0.55, 0.42, 0.45, 0.60, 0.48),
        trait_variance=_v(0.08, 0.07, 0.09, 0.10, 0.09, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Starts free trial, converts if ROI is clear within 14 days",
        known_failure_modes=[
            "No free trial → high friction drop-off",
            "ROI not demonstrated during trial → churns",
        ],
        product_affinities=["saas", "productivity_tool", "marketplace"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "26-40", "device_primary": "desktop"},
    ),

    "urban_mid_income_hardware_considerer": ClusterDefinition(
        cluster_id="urban_mid_income_hardware_considerer",
        name="Urban mid-income hardware considerer",
        description="Mid-income urban buyer researching hardware for 2-6 weeks before purchasing.",
        population_weight=0.04,
        base_traits=_t(0.52, 0.68, 0.65, 0.52, 0.50, 0.50, 0.55, 0.52),
        trait_variance=_v(0.08, 0.08, 0.10, 0.10, 0.09, 0.10, 0.10, 0.10),
        dominant_behavior_pattern="Compares 3-5 options on aggregator sites, decides on EMI availability",
        known_failure_modes=[
            "No EMI option → drops at checkout",
            "Price higher than Amazon listing → bounces",
        ],
        product_affinities=["consumer_hardware", "iot_hardware", "smart_home", "health_hardware"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "28-45", "device_primary": "mobile"},
    ),

    "young_urban_professional_first_job": ClusterDefinition(
        cluster_id="young_urban_professional_first_job",
        name="Young urban professional, first job",
        description="22-27 year old in first or second job, high aspiration, constrained budget.",
        population_weight=0.05,
        base_traits=_t(0.38, 0.80, 0.82, 0.55, 0.68, 0.40, 0.58, 0.72),
        trait_variance=_v(0.07, 0.06, 0.08, 0.10, 0.09, 0.09, 0.09, 0.09),
        dominant_behavior_pattern="Converts on freemium or low entry price; upgrades if value is visceral",
        known_failure_modes=[
            "Price > ₹500/month at cold start → exit",
            "No mobile-first experience → exits immediately",
        ],
        product_affinities=["consumer_app", "saas", "marketplace", "d2c"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "22-27", "device_primary": "mobile"},
    ),

    "urban_couple_joint_purchaser": ClusterDefinition(
        cluster_id="urban_couple_joint_purchaser",
        name="Urban couple joint purchaser",
        description="Dual-income couple making a shared household purchase decision.",
        population_weight=0.03,
        base_traits=_t(0.62, 0.70, 0.70, 0.58, 0.40, 0.48, 0.55, 0.65),
        trait_variance=_v(0.07, 0.08, 0.10, 0.10, 0.09, 0.09, 0.10, 0.09),
        dominant_behavior_pattern="One partner researches, joint final decision; gift-wrapping matters",
        known_failure_modes=[
            "Solo account structure → friction for shared use",
            "No family/couples plan → reverts to cheaper alternative",
        ],
        product_affinities=["consumer_app", "smart_home", "d2c", "health_hardware"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "28-40", "device_primary": "mobile"},
    ),

    "mid_income_startup_founder": ClusterDefinition(
        cluster_id="mid_income_startup_founder",
        name="Mid-income startup founder",
        description="Early-stage founder bootstrapping or lightly funded, high digital literacy.",
        population_weight=0.02,
        base_traits=_t(0.45, 0.88, 0.90, 0.52, 0.60, 0.38, 0.75, 0.62),
        trait_variance=_v(0.09, 0.05, 0.07, 0.10, 0.10, 0.08, 0.08, 0.09),
        dominant_behavior_pattern="Adopts tools quickly if ROI is fast; churns when runway shrinks",
        known_failure_modes=[
            "Annual pricing only → can't commit",
            "Enterprise sales cycle → wrong fit",
        ],
        product_affinities=["saas", "developer_tool", "productivity_tool", "marketplace"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "24-38", "device_primary": "desktop"},
    ),

    "urban_working_mother": ClusterDefinition(
        cluster_id="urban_working_mother",
        name="Urban working mother",
        description="Time-scarce professional mother making considered purchases for family wellbeing.",
        population_weight=0.03,
        base_traits=_t(0.58, 0.70, 0.78, 0.62, 0.48, 0.45, 0.52, 0.68),
        trait_variance=_v(0.08, 0.08, 0.08, 0.09, 0.09, 0.09, 0.09, 0.09),
        dominant_behavior_pattern="Converts on safety, time-saving, and trusted peer recommendation",
        known_failure_modes=[
            "Long onboarding → exits on step 2",
            "No safety/ingredient transparency → blocks purchase",
        ],
        product_affinities=["consumer_app", "d2c", "health_hardware"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "30-44", "device_primary": "mobile"},
    ),

    # ── Students ─────────────────────────────────────────────────────────

    "high_literacy_student_freemium_ceiling": ClusterDefinition(
        cluster_id="high_literacy_student_freemium_ceiling",
        name="High-literacy student with freemium ceiling",
        description="Tech-savvy student who uses freemium heavily but rarely upgrades.",
        population_weight=0.04,
        base_traits=_t(0.22, 0.82, 0.78, 0.55, 0.85, 0.42, 0.62, 0.70),
        trait_variance=_v(0.05, 0.06, 0.08, 0.10, 0.06, 0.09, 0.09, 0.09),
        dominant_behavior_pattern="Exhausts free tier, seeks workarounds, converts only under deadline",
        known_failure_modes=[
            "Hard paywall too early → finds free alternative",
            "No student discount → perpetual free tier user",
        ],
        product_affinities=["consumer_app", "saas", "developer_tool"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "18-23", "device_primary": "mobile"},
    ),

    "low_literacy_student_passive": ClusterDefinition(
        cluster_id="low_literacy_student_passive",
        name="Low-literacy student (passive consumer)",
        description="Student with limited digital skill who discovers products via social media passively.",
        population_weight=0.03,
        base_traits=_t(0.18, 0.35, 0.55, 0.50, 0.90, 0.60, 0.40, 0.78),
        trait_variance=_v(0.05, 0.09, 0.10, 0.12, 0.06, 0.10, 0.10, 0.09),
        dominant_behavior_pattern="Discovers via Reels/Shorts, clicks through, drops at complex signup",
        known_failure_modes=[
            "Registration requires email/corporate login → drops",
            "No vernacular language support → confused and exits",
        ],
        product_affinities=["consumer_app", "d2c"],
        demographic_profile={"geography": "tier2_tier3", "age_bracket": "17-22", "device_primary": "mobile"},
    ),

    "student_high_intent_specific_need": ClusterDefinition(
        cluster_id="student_high_intent_specific_need",
        name="Student with high intent, specific need",
        description="Student with an urgent specific need (exam prep, job hunt) converting for a defined purpose.",
        population_weight=0.03,
        base_traits=_t(0.20, 0.72, 0.88, 0.58, 0.80, 0.35, 0.65, 0.60),
        trait_variance=_v(0.05, 0.08, 0.07, 0.10, 0.07, 0.08, 0.09, 0.10),
        dominant_behavior_pattern="Converts fast when product directly addresses named need; churns after need is met",
        known_failure_modes=[
            "Generic positioning → doesn't see specific use case",
            "No outcome promise → hesitates",
        ],
        product_affinities=["consumer_app", "saas", "marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "18-25", "device_primary": "mobile"},
    ),

    "college_group_purchase": ClusterDefinition(
        cluster_id="college_group_purchase",
        name="College group purchaser",
        description="Student who buys or shares a subscription as part of a friend group.",
        population_weight=0.02,
        base_traits=_t(0.20, 0.65, 0.72, 0.60, 0.88, 0.38, 0.55, 0.88),
        trait_variance=_v(0.05, 0.09, 0.10, 0.10, 0.07, 0.09, 0.10, 0.08),
        dominant_behavior_pattern="One person pays, shared among 3-6; cancels if anyone leaves the group",
        known_failure_modes=[
            "No shared-account or family plan → uses workarounds or drops",
            "No UPI/WhatsApp pay → checkout friction",
        ],
        product_affinities=["consumer_app", "d2c"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "18-23", "device_primary": "mobile"},
    ),

    "recent_graduate_job_seeker": ClusterDefinition(
        cluster_id="recent_graduate_job_seeker",
        name="Recent graduate job seeker",
        description="Fresh graduate investing in career tools but highly price-sensitive.",
        population_weight=0.02,
        base_traits=_t(0.22, 0.75, 0.85, 0.55, 0.82, 0.38, 0.62, 0.65),
        trait_variance=_v(0.05, 0.07, 0.07, 0.10, 0.07, 0.08, 0.09, 0.10),
        dominant_behavior_pattern="Converts on free trial + outcome story; churns after job offer",
        known_failure_modes=[
            "No free tier or trial → blocked",
            "No success stories from peers → doesn't trust value",
        ],
        product_affinities=["saas", "marketplace", "consumer_app"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "21-26", "device_primary": "mobile"},
    ),

    # ── Tier-2 / Tier-3 consumers ─────────────────────────────────────────

    "tier2_aspirational_founder": ClusterDefinition(
        cluster_id="tier2_aspirational_founder",
        name="Tier-2 aspirational founder",
        description="First-generation entrepreneur from a non-metro city, high motivation, limited runway.",
        population_weight=0.03,
        base_traits=_t(0.35, 0.68, 0.88, 0.50, 0.72, 0.42, 0.68, 0.60),
        trait_variance=_v(0.08, 0.09, 0.07, 0.10, 0.09, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Converts on perceived ROI; churns if value isn't felt in 7 days",
        known_failure_modes=[
            "English-only onboarding → comprehension barrier",
            "No cash/UPI payment → checkout failure",
        ],
        product_affinities=["saas", "marketplace", "productivity_tool"],
        demographic_profile={"geography": "tier2", "age_bracket": "24-38", "device_primary": "mobile"},
    ),

    "tier2_established_business_owner": ClusterDefinition(
        cluster_id="tier2_established_business_owner",
        name="Tier-2 established business owner",
        description="Profitable SME owner in a tier-2 city, trusts referrals, distrusts online-first products.",
        population_weight=0.03,
        base_traits=_t(0.58, 0.48, 0.65, 0.42, 0.58, 0.60, 0.45, 0.55),
        trait_variance=_v(0.08, 0.10, 0.10, 0.12, 0.10, 0.10, 0.10, 0.10),
        dominant_behavior_pattern="Buys only after colleague vouches; needs phone/WhatsApp support",
        known_failure_modes=[
            "No WhatsApp/phone support → trust gap",
            "Complex digital onboarding → abandons",
        ],
        product_affinities=["saas", "marketplace", "b2b_marketplace"],
        demographic_profile={"geography": "tier2", "age_bracket": "35-55", "device_primary": "mobile"},
    ),

    "tier3_first_time_app_user": ClusterDefinition(
        cluster_id="tier3_first_time_app_user",
        name="Tier-3 first-time app user",
        description="Rural/small-town consumer using a smartphone app for one of the first times.",
        population_weight=0.04,
        base_traits=_t(0.25, 0.28, 0.65, 0.45, 0.88, 0.70, 0.35, 0.72),
        trait_variance=_v(0.07, 0.08, 0.10, 0.12, 0.06, 0.10, 0.10, 0.09),
        dominant_behavior_pattern="Converts if someone nearby explains it; drops immediately on confusion",
        known_failure_modes=[
            "No vernacular language → instant drop",
            "More than 2 steps to first value → exits",
        ],
        product_affinities=["consumer_app", "d2c"],
        demographic_profile={"geography": "tier3_rural", "age_bracket": "18-40", "device_primary": "mobile"},
    ),

    "tier2_price_sensitive_pragmatist": ClusterDefinition(
        cluster_id="tier2_price_sensitive_pragmatist",
        name="Tier-2 price-sensitive pragmatist",
        description="Middle-class tier-2 buyer who wants functional value at the lowest price.",
        population_weight=0.04,
        base_traits=_t(0.40, 0.58, 0.68, 0.52, 0.82, 0.55, 0.50, 0.50),
        trait_variance=_v(0.08, 0.09, 0.09, 0.10, 0.08, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Compares aggressively on price, converts if cheapest credible option",
        known_failure_modes=[
            "Competitor priced 10% lower → lost",
            "No clearly stated price on landing page → exits",
        ],
        product_affinities=["consumer_app", "d2c", "marketplace"],
        demographic_profile={"geography": "tier2", "age_bracket": "25-45", "device_primary": "mobile"},
    ),

    "tier3_community_influenced_buyer": ClusterDefinition(
        cluster_id="tier3_community_influenced_buyer",
        name="Tier-3 community-influenced buyer",
        description="Rural buyer whose purchase is primarily determined by local community norms.",
        population_weight=0.03,
        base_traits=_t(0.28, 0.32, 0.60, 0.48, 0.85, 0.65, 0.38, 0.90),
        trait_variance=_v(0.07, 0.09, 0.10, 0.12, 0.07, 0.10, 0.10, 0.08),
        dominant_behavior_pattern="Only buys what the local trusted person or relative already uses",
        known_failure_modes=[
            "No community ambassador program → zero penetration",
            "National ad campaign without local face → ignored",
        ],
        product_affinities=["d2c", "consumer_app"],
        demographic_profile={"geography": "tier3_rural", "age_bracket": "20-50", "device_primary": "mobile"},
    ),

    "tier2_educated_young_parent": ClusterDefinition(
        cluster_id="tier2_educated_young_parent",
        name="Tier-2 educated young parent",
        description="College-educated parent in a tier-2 city investing in children's education and health.",
        population_weight=0.03,
        base_traits=_t(0.42, 0.62, 0.78, 0.58, 0.65, 0.50, 0.55, 0.65),
        trait_variance=_v(0.08, 0.09, 0.09, 0.10, 0.09, 0.09, 0.10, 0.09),
        dominant_behavior_pattern="Converts on safety and outcome evidence; highly receptive to referrals",
        known_failure_modes=[
            "No Tamil/Hindi/regional language option → hesitates",
            "No refund/return guarantee → blocks purchase",
        ],
        product_affinities=["consumer_app", "d2c", "marketplace"],
        demographic_profile={"geography": "tier2", "age_bracket": "26-40", "device_primary": "mobile"},
    ),

    # ── SMB / B2B ────────────────────────────────────────────────────────

    "smb_owner_self_serve": ClusterDefinition(
        cluster_id="smb_owner_self_serve",
        name="SMB owner (self-serve)",
        description="Small business owner who discovers and adopts tools independently without sales assistance.",
        population_weight=0.03,
        base_traits=_t(0.50, 0.70, 0.75, 0.52, 0.60, 0.45, 0.62, 0.48),
        trait_variance=_v(0.08, 0.08, 0.09, 0.10, 0.10, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Signs up, tests for 14 days, converts if saves >2 hrs/week",
        known_failure_modes=[
            "No self-serve plan below ₹2,000/month → escalates or drops",
            "Complex onboarding requiring team setup → abandons solo",
        ],
        product_affinities=["saas", "productivity_tool", "marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "28-48", "device_primary": "desktop"},
    ),

    "smb_owner_referral_dependent": ClusterDefinition(
        cluster_id="smb_owner_referral_dependent",
        name="SMB owner (referral-dependent)",
        description="Small business owner who only adopts tools vouched for by a peer in their network.",
        population_weight=0.03,
        base_traits=_t(0.50, 0.55, 0.68, 0.42, 0.62, 0.58, 0.48, 0.58),
        trait_variance=_v(0.08, 0.09, 0.10, 0.12, 0.10, 0.10, 0.10, 0.10),
        dominant_behavior_pattern="Will not buy from a brand they have not heard of from someone they trust",
        known_failure_modes=[
            "No case study from similar industry → won't commit",
            "Cold outreach → instinctive distrust",
        ],
        product_affinities=["saas", "b2b_marketplace", "marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "30-52", "device_primary": "mobile"},
    ),

    "mid_market_it_decision_maker": ClusterDefinition(
        cluster_id="mid_market_it_decision_maker",
        name="Mid-market IT decision maker",
        description="IT head or CTO of a 50-500 person company evaluating technical products.",
        population_weight=0.02,
        base_traits=_t(0.68, 0.85, 0.70, 0.50, 0.35, 0.60, 0.62, 0.42),
        trait_variance=_v(0.07, 0.05, 0.09, 0.10, 0.07, 0.09, 0.09, 0.09),
        dominant_behavior_pattern="Runs 30-day PoC, requires API docs and SSO, then presents to CFO",
        known_failure_modes=[
            "No API/SSO documentation → eliminated in technical review",
            "No SOC 2 or equivalent → security review blocker",
        ],
        product_affinities=["saas", "developer_tool", "enterprise_software"],
        demographic_profile={"geography": "metro", "age_bracket": "30-50", "device_primary": "desktop"},
    ),

    "enterprise_procurement_gatekeeper": ClusterDefinition(
        cluster_id="enterprise_procurement_gatekeeper",
        name="Enterprise procurement gatekeeper",
        description="Procurement manager enforcing vendor policy and cost controls in a large enterprise.",
        population_weight=0.01,
        base_traits=_t(0.75, 0.62, 0.50, 0.42, 0.25, 0.80, 0.40, 0.35),
        trait_variance=_v(0.06, 0.08, 0.10, 0.12, 0.06, 0.08, 0.10, 0.09),
        dominant_behavior_pattern="Blocks any vendor not on approved list; primary driver is compliance",
        known_failure_modes=[
            "Not on vendor panel → cannot proceed",
            "No MSA/DPA template → legal stall",
        ],
        product_affinities=["enterprise_software", "saas"],
        demographic_profile={"geography": "metro", "age_bracket": "32-55", "device_primary": "desktop"},
    ),

    "technical_founder_evaluator": ClusterDefinition(
        cluster_id="technical_founder_evaluator",
        name="Technical founder evaluator",
        description="CTO or technical co-founder evaluating infrastructure or dev tooling.",
        population_weight=0.02,
        base_traits=_t(0.48, 0.95, 0.85, 0.52, 0.55, 0.30, 0.78, 0.52),
        trait_variance=_v(0.08, 0.03, 0.07, 0.10, 0.10, 0.07, 0.07, 0.10),
        dominant_behavior_pattern="Reads source code or API docs before pricing page; converts on docs quality",
        known_failure_modes=[
            "No public docs or GitHub → disqualified immediately",
            "Slow API response in demo → rejected",
        ],
        product_affinities=["developer_tool", "saas", "enterprise_software"],
        demographic_profile={"geography": "metro", "age_bracket": "24-40", "device_primary": "desktop"},
    ),

    "non_technical_co_founder_buyer": ClusterDefinition(
        cluster_id="non_technical_co_founder_buyer",
        name="Non-technical co-founder buyer",
        description="Business/product co-founder making tool purchasing decisions without engineering input.",
        population_weight=0.02,
        base_traits=_t(0.45, 0.62, 0.80, 0.55, 0.58, 0.38, 0.65, 0.60),
        trait_variance=_v(0.08, 0.09, 0.08, 0.10, 0.10, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Converts on case studies and clear ROI; relies on G2/Capterra scores",
        known_failure_modes=[
            "Technical jargon on landing page → confusion drop",
            "No 'no-code' or 'easy setup' signal → thinks it requires dev resources",
        ],
        product_affinities=["saas", "productivity_tool", "marketplace"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "26-42", "device_primary": "desktop"},
    ),

    # ── Hardware-specific ─────────────────────────────────────────────────

    "early_hardware_adopter_tech_enthusiast": ClusterDefinition(
        cluster_id="early_hardware_adopter_tech_enthusiast",
        name="Early hardware adopter (tech enthusiast)",
        description="Hobbyist or enthusiast who buys new hardware categories early purely for novelty.",
        population_weight=0.02,
        base_traits=_t(0.58, 0.88, 0.90, 0.60, 0.28, 0.22, 0.78, 0.68),
        trait_variance=_v(0.07, 0.05, 0.07, 0.10, 0.07, 0.06, 0.07, 0.09),
        dominant_behavior_pattern="Pre-orders on Kickstarter/Indiegogo; shares unboxing; returns if disappoints",
        known_failure_modes=[
            "No crowdfunding/pre-order campaign → waits for public launch",
            "No community/Discord for product → loses excitement",
        ],
        product_affinities=["consumer_hardware", "wearable", "iot_hardware", "smart_home", "health_hardware"],
        demographic_profile={"geography": "metro", "age_bracket": "22-38", "device_primary": "desktop"},
    ),

    "considered_hardware_researcher": ClusterDefinition(
        cluster_id="considered_hardware_researcher",
        name="Considered hardware researcher",
        description="Methodical buyer who spends 3-8 weeks comparing hardware options before committing.",
        population_weight=0.03,
        base_traits=_t(0.60, 0.78, 0.72, 0.55, 0.40, 0.52, 0.55, 0.48),
        trait_variance=_v(0.07, 0.07, 0.09, 0.10, 0.08, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Reads 10+ reviews, watches 5+ videos, buys from most authoritative source",
        known_failure_modes=[
            "No long-form comparison content → excluded from shortlist",
            "Unavailable on Amazon/Flipkart → won't buy direct",
        ],
        product_affinities=["consumer_hardware", "iot_hardware", "smart_home"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "28-48", "device_primary": "desktop"},
    ),

    "value_hardware_buyer": ClusterDefinition(
        cluster_id="value_hardware_buyer",
        name="Value hardware buyer",
        description="Purchases hardware primarily on price-to-performance ratio.",
        population_weight=0.03,
        base_traits=_t(0.42, 0.62, 0.65, 0.52, 0.78, 0.52, 0.50, 0.48),
        trait_variance=_v(0.08, 0.09, 0.10, 0.10, 0.08, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Converts on 'best under ₹X' positioning; sensitive to 5% price difference",
        known_failure_modes=[
            "Competing product ₹300 cheaper with similar specs → lost",
            "No value-tier SKU → exits to competitor",
        ],
        product_affinities=["consumer_hardware", "d2c"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "25-45", "device_primary": "mobile"},
    ),

    "gift_hardware_buyer": ClusterDefinition(
        cluster_id="gift_hardware_buyer",
        name="Gift hardware buyer",
        description="Buying hardware as a gift; low personal knowledge, high brand trust requirement.",
        population_weight=0.02,
        base_traits=_t(0.55, 0.55, 0.70, 0.60, 0.48, 0.50, 0.48, 0.68),
        trait_variance=_v(0.08, 0.10, 0.10, 0.10, 0.09, 0.10, 0.10, 0.09),
        dominant_behavior_pattern="Buys brand they recognise; gift wrapping and packaging are deciding factors",
        known_failure_modes=[
            "No gift packaging option → drops to Amazon",
            "Unknown brand at same price as known brand → loses",
        ],
        product_affinities=["consumer_hardware", "wearable", "d2c", "health_hardware"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "25-55", "device_primary": "mobile"},
    ),

    "replacement_hardware_buyer": ClusterDefinition(
        cluster_id="replacement_hardware_buyer",
        name="Replacement hardware buyer",
        description="Replacing a broken or outdated device; urgency-driven, brand-loyal.",
        population_weight=0.02,
        base_traits=_t(0.52, 0.65, 0.72, 0.60, 0.50, 0.42, 0.60, 0.45),
        trait_variance=_v(0.08, 0.09, 0.09, 0.10, 0.09, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Re-buys same brand if satisfied; switches only if previous was bad",
        known_failure_modes=[
            "No expedited delivery option → waits for sale elsewhere",
            "No loyalty discount for returning buyer → feels undervalued",
        ],
        product_affinities=["consumer_hardware", "iot_hardware", "smart_home"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "28-50", "device_primary": "mobile"},
    ),

    # ── Health hardware ───────────────────────────────────────────────────

    "health_hardware_skeptic": ClusterDefinition(
        cluster_id="health_hardware_skeptic",
        name="Health hardware skeptic",
        description="Interested in health outcomes but unconvinced by wearable/health tech claims.",
        population_weight=0.02,
        base_traits=_t(0.55, 0.68, 0.62, 0.42, 0.55, 0.62, 0.52, 0.50),
        trait_variance=_v(0.08, 0.08, 0.10, 0.12, 0.09, 0.10, 0.10, 0.10),
        dominant_behavior_pattern="Needs clinical study or doctor endorsement before considering purchase",
        known_failure_modes=[
            "Marketing language only, no evidence → instant distrust",
            "No return policy → won't risk it",
        ],
        product_affinities=["health_hardware"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "30-55", "device_primary": "mobile"},
    ),

    "health_hardware_enthusiast": ClusterDefinition(
        cluster_id="health_hardware_enthusiast",
        name="Health hardware enthusiast",
        description="Fitness-focused buyer who tracks metrics obsessively and upgrades frequently.",
        population_weight=0.02,
        base_traits=_t(0.65, 0.80, 0.88, 0.65, 0.30, 0.25, 0.72, 0.62),
        trait_variance=_v(0.07, 0.06, 0.07, 0.09, 0.07, 0.07, 0.08, 0.09),
        dominant_behavior_pattern="Upgrades every 18 months; converts on data accuracy and sensor specs",
        known_failure_modes=[
            "Accuracy not independently verified → skeptical",
            "No integration with Strava/Apple Health → dealbreaker",
        ],
        product_affinities=["health_hardware", "consumer_app"],
        demographic_profile={"geography": "metro", "age_bracket": "24-45", "device_primary": "mobile"},
    ),

    "smart_home_early_adopter": ClusterDefinition(
        cluster_id="smart_home_early_adopter",
        name="Smart home early adopter",
        description="Enthusiast building a connected home; ecosystem lock-in is a key concern.",
        population_weight=0.02,
        base_traits=_t(0.68, 0.85, 0.85, 0.58, 0.28, 0.28, 0.72, 0.60),
        trait_variance=_v(0.07, 0.06, 0.07, 0.10, 0.07, 0.07, 0.08, 0.10),
        dominant_behavior_pattern="Buys if compatible with existing ecosystem; researches API availability",
        known_failure_modes=[
            "Not compatible with Google Home or Alexa → eliminated",
            "No local control option → privacy concern blocks purchase",
        ],
        product_affinities=["smart_home", "iot_hardware", "consumer_hardware"],
        demographic_profile={"geography": "metro", "age_bracket": "26-45", "device_primary": "mobile"},
    ),

    # ── Behavioural / psychographic clusters ─────────────────────────────

    "anxiety_driven_researcher": ClusterDefinition(
        cluster_id="anxiety_driven_researcher",
        name="Anxiety-driven researcher",
        description="Over-researches every purchase due to fear of making the wrong decision.",
        population_weight=0.03,
        base_traits=_t(0.52, 0.72, 0.75, 0.45, 0.58, 0.72, 0.40, 0.52),
        trait_variance=_v(0.08, 0.08, 0.09, 0.12, 0.09, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Opens 20+ tabs, reads every review, abandons cart 3 times before buying",
        known_failure_modes=[
            "No money-back guarantee → paralysed",
            "Any negative review visible → deters conversion",
        ],
        product_affinities=["consumer_app", "saas", "consumer_hardware", "wearable", "iot_hardware", "d2c"],
        demographic_profile={"geography": "metro_tier1", "age_bracket": "25-45", "device_primary": "desktop"},
    ),

    "impulsive_trend_follower": ClusterDefinition(
        cluster_id="impulsive_trend_follower",
        name="Impulsive trend follower",
        description="Converts quickly on trending social content; churns just as fast.",
        population_weight=0.04,
        base_traits=_t(0.45, 0.68, 0.80, 0.60, 0.55, 0.25, 0.35, 0.88),
        trait_variance=_v(0.09, 0.09, 0.09, 0.10, 0.10, 0.08, 0.09, 0.08),
        dominant_behavior_pattern="Sees Reel → clicks → buys → forgets in 2 weeks",
        known_failure_modes=[
            "No urgency/scarcity signal → decides to 'check later', never returns",
            "Onboarding longer than 60 seconds → drops",
        ],
        product_affinities=["consumer_app", "d2c"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "18-32", "device_primary": "mobile"},
    ),

    "loyalist_returning_buyer": ClusterDefinition(
        cluster_id="loyalist_returning_buyer",
        name="Loyalist / returning buyer",
        description="Previous customer or long-time subscriber who consistently re-purchases.",
        population_weight=0.03,
        base_traits=_t(0.58, 0.70, 0.72, 0.78, 0.38, 0.40, 0.65, 0.55),
        trait_variance=_v(0.08, 0.08, 0.09, 0.08, 0.08, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Renews automatically; only churns if product degrades or price spikes",
        known_failure_modes=[
            "Price increase >20% with no communication → cancels",
            "Product regression in core feature → switches",
        ],
        product_affinities=["saas", "consumer_app", "d2c", "marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "28-55", "device_primary": "mobile"},
    ),

    "price_anchor_manipulated_buyer": ClusterDefinition(
        cluster_id="price_anchor_manipulated_buyer",
        name="Price-anchor manipulated buyer",
        description="Responds strongly to anchoring effects (crossed-out prices, 'originally ₹X').",
        population_weight=0.03,
        base_traits=_t(0.45, 0.58, 0.68, 0.55, 0.72, 0.45, 0.48, 0.62),
        trait_variance=_v(0.09, 0.10, 0.10, 0.10, 0.09, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Converts when 'deal' framing is prominent; regrets and returns if anchor was false",
        known_failure_modes=[
            "No visible original/compared price → misses the 'deal' signal",
            "Discount seems too large → suspects quality",
        ],
        product_affinities=["d2c", "marketplace", "consumer_app"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "22-48", "device_primary": "mobile"},
    ),

    "peer_pressure_converter": ClusterDefinition(
        cluster_id="peer_pressure_converter",
        name="Peer-pressure converter",
        description="Converts because peers or colleagues visibly use the product.",
        population_weight=0.03,
        base_traits=_t(0.48, 0.65, 0.72, 0.58, 0.60, 0.40, 0.50, 0.85),
        trait_variance=_v(0.09, 0.09, 0.09, 0.10, 0.10, 0.09, 0.10, 0.08),
        dominant_behavior_pattern="Buys after 3rd peer mention; heavy word-of-mouth dependency",
        known_failure_modes=[
            "No network within product (no sharing/inviting feature) → loses peer signal",
            "Product not visually brandable → peers can't show it off",
        ],
        product_affinities=["consumer_app", "d2c", "saas"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "20-38", "device_primary": "mobile"},
    ),

    "deliberate_minimalist": ClusterDefinition(
        cluster_id="deliberate_minimalist",
        name="Deliberate minimalist",
        description="Intentionally avoids excess subscriptions and products; very hard to convert.",
        population_weight=0.02,
        base_traits=_t(0.60, 0.78, 0.55, 0.65, 0.62, 0.65, 0.75, 0.40),
        trait_variance=_v(0.08, 0.07, 0.10, 0.09, 0.09, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Converts only if product replaces 2+ existing tools and saves money",
        known_failure_modes=[
            "Positioned as add-on (not consolidation) → rejected",
            "Any feature bloat visible → opts out",
        ],
        product_affinities=["saas", "productivity_tool"],
        demographic_profile={"geography": "metro", "age_bracket": "28-50", "device_primary": "desktop"},
    ),

    "productivity_maximiser": ClusterDefinition(
        cluster_id="productivity_maximiser",
        name="Productivity maximiser",
        description="Converts on any credible time-saving claim; power user archetype.",
        population_weight=0.03,
        base_traits=_t(0.62, 0.85, 0.88, 0.60, 0.40, 0.30, 0.80, 0.48),
        trait_variance=_v(0.08, 0.05, 0.07, 0.09, 0.09, 0.08, 0.07, 0.10),
        dominant_behavior_pattern="Converts on headline ROI (saves 3hr/week); becomes power user if true",
        known_failure_modes=[
            "Time-saving claim not demonstrated in trial → churns day 7",
            "Keyboard shortcuts missing → frustration churn",
        ],
        product_affinities=["saas", "productivity_tool", "developer_tool"],
        demographic_profile={"geography": "metro", "age_bracket": "24-42", "device_primary": "desktop"},
    ),

    "budget_constrained_high_intent": ClusterDefinition(
        cluster_id="budget_constrained_high_intent",
        name="Budget-constrained high-intent buyer",
        description="Genuinely wants the product but cannot afford it at current price; converts on discount.",
        population_weight=0.04,
        base_traits=_t(0.28, 0.68, 0.85, 0.58, 0.90, 0.42, 0.55, 0.58),
        trait_variance=_v(0.07, 0.08, 0.07, 0.10, 0.07, 0.09, 0.09, 0.10),
        dominant_behavior_pattern="Wishlists, waits for sale, converts on any discount; highest LTV if retained",
        known_failure_modes=[
            "No sale/discount in 90 days → finds alternative",
            "No waitlist or notify-on-sale feature → forgets product",
        ],
        product_affinities=["consumer_app", "d2c", "marketplace", "saas"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "20-35", "device_primary": "mobile"},
    ),

    "passive_enterprise_user": ClusterDefinition(
        cluster_id="passive_enterprise_user",
        name="Passive enterprise user",
        description="Individual contributor using a tool mandated by their company; low personal agency.",
        population_weight=0.02,
        base_traits=_t(0.65, 0.68, 0.45, 0.60, 0.30, 0.55, 0.50, 0.42),
        trait_variance=_v(0.07, 0.08, 0.10, 0.09, 0.07, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Uses because required; becomes advocate only if product is genuinely excellent",
        known_failure_modes=[
            "Poor UX → complaints escalate to IT → churn risk for whole account",
            "No end-user onboarding → low adoption, procurement drops renewal",
        ],
        product_affinities=["enterprise_software", "saas"],
        demographic_profile={"geography": "metro", "age_bracket": "24-50", "device_primary": "desktop"},
    ),

    "burnt_previously_buyer": ClusterDefinition(
        cluster_id="burnt_previously_buyer",
        name="Burnt previously buyer",
        description="Had a bad experience with a similar product and is deeply skeptical of the category.",
        population_weight=0.02,
        base_traits=_t(0.52, 0.65, 0.60, 0.32, 0.62, 0.72, 0.55, 0.48),
        trait_variance=_v(0.08, 0.09, 0.10, 0.12, 0.09, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Converts only with free trial + money-back + testimonials from similar users",
        known_failure_modes=[
            "No free trial → won't risk money again",
            "No money-back guarantee → conversion wall",
        ],
        product_affinities=["saas", "consumer_app", "d2c", "marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "26-50", "device_primary": "mobile"},
    ),

    # ── 5 additional clusters to reach 52 ────────────────────────────────

    "retiree_digital_explorer": ClusterDefinition(
        cluster_id="retiree_digital_explorer",
        name="Retiree digital explorer",
        description="65+ retiree who has recently adopted a smartphone and explores apps cautiously.",
        population_weight=0.02,
        base_traits=_t(0.60, 0.25, 0.55, 0.48, 0.60, 0.75, 0.38, 0.60),
        trait_variance=_v(0.08, 0.08, 0.10, 0.12, 0.09, 0.09, 0.10, 0.09),
        dominant_behavior_pattern="Converts if a family member helps; needs large text and simple navigation",
        known_failure_modes=[
            "Complex registration → exits immediately",
            "No vernacular language or voice support → blocked",
        ],
        product_affinities=["consumer_app", "health_hardware", "d2c"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "60-75", "device_primary": "mobile"},
    ),

    "gig_economy_worker": ClusterDefinition(
        cluster_id="gig_economy_worker",
        name="Gig economy worker",
        description="Freelancer or platform gig worker optimising income with minimal tools spend.",
        population_weight=0.02,
        base_traits=_t(0.32, 0.62, 0.78, 0.52, 0.82, 0.40, 0.55, 0.60),
        trait_variance=_v(0.08, 0.09, 0.09, 0.10, 0.08, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Converts on income-multiplying ROI; churns the moment a cheaper substitute appears",
        known_failure_modes=[
            "No clear income uplift story → skips",
            "Monthly cost > ₹300 → too expensive relative to gig earnings",
        ],
        product_affinities=["marketplace", "saas", "consumer_app"],
        demographic_profile={"geography": "metro_tier1_tier2_tier3", "age_bracket": "22-42", "device_primary": "mobile"},
    ),

    "ngo_nonprofit_buyer": ClusterDefinition(
        cluster_id="ngo_nonprofit_buyer",
        name="NGO / nonprofit buyer",
        description="Programme officer or admin at an NGO procuring tools on a restricted budget.",
        population_weight=0.01,
        base_traits=_t(0.38, 0.60, 0.70, 0.55, 0.88, 0.55, 0.58, 0.55),
        trait_variance=_v(0.08, 0.10, 0.10, 0.10, 0.07, 0.09, 0.10, 0.10),
        dominant_behavior_pattern="Requires nonprofit discount; decision goes through committee; very slow cycle",
        known_failure_modes=[
            "No nonprofit pricing or grant-eligible tier → can't justify",
            "No offline functionality → excluded for field use",
        ],
        product_affinities=["saas", "productivity_tool", "b2b_marketplace"],
        demographic_profile={"geography": "metro_tier1_tier2", "age_bracket": "28-50", "device_primary": "desktop"},
    ),

    "diaspora_remittance_buyer": ClusterDefinition(
        cluster_id="diaspora_remittance_buyer",
        name="Diaspora / NRI remittance buyer",
        description="Indian diaspora member purchasing for a family member back in India.",
        population_weight=0.01,
        base_traits=_t(0.75, 0.80, 0.72, 0.60, 0.38, 0.38, 0.60, 0.65),
        trait_variance=_v(0.07, 0.07, 0.10, 0.10, 0.08, 0.09, 0.10, 0.09),
        dominant_behavior_pattern="Converts on India-specific trust signals and gift/delivery options",
        known_failure_modes=[
            "No international card acceptance → checkout failure",
            "No gift delivery or COD option for recipient → loses",
        ],
        product_affinities=["d2c", "consumer_app", "consumer_hardware", "wearable"],
        demographic_profile={"geography": "international", "age_bracket": "25-55", "device_primary": "desktop"},
    ),

    "vernacular_content_creator": ClusterDefinition(
        cluster_id="vernacular_content_creator",
        name="Vernacular content creator",
        description="Regional-language YouTuber or influencer monetising an audience in a non-English language.",
        population_weight=0.02,
        base_traits=_t(0.35, 0.60, 0.85, 0.55, 0.72, 0.35, 0.60, 0.80),
        trait_variance=_v(0.08, 0.09, 0.08, 0.10, 0.09, 0.08, 0.09, 0.09),
        dominant_behavior_pattern="Converts on creator monetisation features; evangelises to followers if satisfied",
        known_failure_modes=[
            "English-only UI → functional barrier",
            "No affiliate or referral payout → no incentive to promote",
        ],
        product_affinities=["consumer_app", "marketplace", "saas"],
        demographic_profile={"geography": "tier1_tier2_tier3", "age_bracket": "20-38", "device_primary": "mobile"},
    ),
}

# ---------------------------------------------------------------------------
# Normalise population weights to sum exactly to 1.0.
# This ensures the registry is always consistent even after adding clusters.
# ---------------------------------------------------------------------------
_raw_total = sum(c.population_weight for c in _CLUSTERS.values())
_normalised_weights = {
    cid: round(c.population_weight / _raw_total, 6)
    for cid, c in _CLUSTERS.items()
}
_weight_residual = round(1.0 - sum(_normalised_weights.values()), 6)
if _weight_residual:
    _anchor_cluster_id = max(
        _normalised_weights,
        key=lambda cid: _normalised_weights[cid],
    )
    _normalised_weights[_anchor_cluster_id] = round(
        _normalised_weights[_anchor_cluster_id] + _weight_residual,
        6,
    )

_CLUSTERS = {
    cid: ClusterDefinition(
        cluster_id=c.cluster_id,
        name=c.name,
        description=c.description,
        population_weight=_normalised_weights[cid],
        base_traits=c.base_traits,
        trait_variance=c.trait_variance,
        dominant_behavior_pattern=c.dominant_behavior_pattern,
        known_failure_modes=list(c.known_failure_modes),
        product_affinities=list(c.product_affinities),
        demographic_profile=dict(c.demographic_profile),
    )
    for cid, c in _CLUSTERS.items()
}

_WEIGHT_SUM = sum(c.population_weight for c in _CLUSTERS.values())
assert abs(_WEIGHT_SUM - 1.0) <= 0.001, (
    f"ClusterRegistry: population weights sum to {_WEIGHT_SUM:.6f}, must be 1.000 ± 0.001"
)
assert len(_CLUSTERS) == 52, (
    f"ClusterRegistry: expected 52 clusters, got {len(_CLUSTERS)}"
)


# ---------------------------------------------------------------------------
# ClusterRegistry
# ---------------------------------------------------------------------------

class ClusterRegistry:
    """
    Access point for all 52 TheCee consumer clusters.

    Usage:
        registry = ClusterRegistry()
        clusters = registry.all_clusters()                  # list of 52
        cluster  = registry.get_cluster("metro_power_professional")
        saas     = registry.clusters_for_product_type("saas")
        ok       = registry.total_weight_check()            # True
        registry.sync_to_db(db_session)                     # on startup

    Performance:
        ``all_clusters()`` and ``clusters_for_product_type()`` are memoised
        at the class level — the registry is immutable after import, so
        repeated calls reuse a single list per product_type. This converts
        O(n) per-call work into O(1) lookups on the conductor hot path.
    """

    _clusters: dict[str, ClusterDefinition] = _CLUSTERS
    _weight_sum: float = _WEIGHT_SUM
    _all_clusters_cache: list[ClusterDefinition] | None = None
    _product_type_cache: dict[str, list[ClusterDefinition]] = {}
    _cache_lock: RLock = RLock()

    def all_clusters(self) -> list[ClusterDefinition]:
        cached = ClusterRegistry._all_clusters_cache
        if cached is not None:
            return cached
        with ClusterRegistry._cache_lock:
            cached = ClusterRegistry._all_clusters_cache
            if cached is None:
                cached = list(self._clusters.values())
                ClusterRegistry._all_clusters_cache = cached
            return cached

    def get_cluster(self, cluster_id: str) -> ClusterDefinition:
        if not isinstance(cluster_id, str) or not cluster_id:
            raise KeyError(
                f"ClusterRegistry.get_cluster requires a non-empty str, "
                f"got {cluster_id!r}"
            )
        try:
            return self._clusters[cluster_id]
        except KeyError:
            raise KeyError(
                f"Unknown cluster_id '{cluster_id}'. "
                f"Valid ids: {sorted(self._clusters.keys())}"
            )

    def clusters_for_product_type(self, product_type: str) -> list[ClusterDefinition]:
        if not isinstance(product_type, str) or not product_type:
            return []
        cached = ClusterRegistry._product_type_cache.get(product_type)
        if cached is not None:
            return cached
        with ClusterRegistry._cache_lock:
            cached = ClusterRegistry._product_type_cache.get(product_type)
            if cached is None:
                cached = [
                    c for c in self._clusters.values()
                    if product_type in c.product_affinities
                ]
                ClusterRegistry._product_type_cache[product_type] = cached
            return cached

    def total_weight_check(self) -> bool:
        # Pre-computed at import — registry is immutable so we can avoid
        # re-summing 52 weights on every call.
        return abs(ClusterRegistry._weight_sum - 1.0) <= 0.001

    def cache_stats(self) -> dict[str, Any]:
        """Diagnostic for tests: counts of cached entries."""
        with ClusterRegistry._cache_lock:
            return {
                "all_clusters_cached": ClusterRegistry._all_clusters_cache is not None,
                "product_types_cached": sorted(
                    ClusterRegistry._product_type_cache.keys()
                ),
                "weight_sum": ClusterRegistry._weight_sum,
            }

    @classmethod
    def reset_cache(cls) -> None:
        """
        Clear memoised caches. Primarily for tests that monkey-patch the
        registry; production code should never need this.
        """
        with cls._cache_lock:
            cls._all_clusters_cache = None
            cls._product_type_cache = {}

    def sync_to_db(self, db_session) -> None:
        """
        Sync cluster base_traits to the cluster_parameters table.

        - Updates base_value for every (cluster_id, trait_name) row.
        - Sets calibrated_value = base_value only when calibration_count = 0
          (i.e. no real data has been collected yet for that parameter).
        - Safe to call on every startup — idempotent.

        Uses a single bulk UPDATE ... FROM (VALUES ...) statement so all 416
        rows are updated in one PostgreSQL round-trip instead of 416 separate
        queries, reducing startup time from ~60 s to under 1 s.
        """
        from sqlalchemy import text

        rows = [
            (cluster.cluster_id, trait_name, float(base_value))
            for cluster in self.all_clusters()
            for trait_name, base_value in cluster.base_traits.items()
        ]

        if not rows:
            return

        # Build named bind parameters for each row so SQLAlchemy can safely
        # interpolate them without any risk of SQL injection.
        placeholders = ", ".join(
            f"(:cid_{i}, :trait_{i}, :val_{i})" for i in range(len(rows))
        )
        params: dict = {}
        for i, (cid, trait, val) in enumerate(rows):
            params[f"cid_{i}"] = cid
            params[f"trait_{i}"] = trait
            params[f"val_{i}"] = val

        db_session.execute(
            text(f"""
                UPDATE cluster_parameters AS cp
                SET
                    base_value       = v.base_value::float,
                    calibrated_value = CASE
                        WHEN cp.calibration_count = 0 THEN v.base_value::float
                        ELSE cp.calibrated_value
                    END
                FROM (VALUES {placeholders}) AS v(cluster_id, trait_name, base_value)
                WHERE cp.cluster_id = v.cluster_id
                AND   cp.trait_name  = v.trait_name
            """),
            params,
        )
        db_session.commit()
