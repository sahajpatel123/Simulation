"""
Claim confidence tagging, specificity scoring, contradiction detection,
and signal quality computation for the TheCee learning system.

Step 36b: these primitives are computed at assumption-extraction time
so every simulation starts with a calibrated signal quality score,
even with zero historical data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Enumerations and multipliers
# ---------------------------------------------------------------------------

class ClaimConfidence(str, Enum):
    VALIDATED_EXTERNAL = "VALIDATED_EXTERNAL"   # real user data / cited research
    VALIDATED_INTERNAL = "VALIDATED_INTERNAL"   # founder-run test / pilot
    DESIGN_INTENT      = "DESIGN_INTENT"        # planned feature, not yet tested
    ASPIRATIONAL       = "ASPIRATIONAL"         # belief / hope with no evidence


CONFIDENCE_MULTIPLIERS: dict[ClaimConfidence, float] = {
    ClaimConfidence.VALIDATED_EXTERNAL: 1.00,
    ClaimConfidence.VALIDATED_INTERNAL: 0.75,
    ClaimConfidence.DESIGN_INTENT:      0.55,
    ClaimConfidence.ASPIRATIONAL:       0.40,
}

# Higher index = higher trust (used to merge heuristics with intake-based claim_confidence)
_CONFIDENCE_RANK: dict[ClaimConfidence, int] = {
    ClaimConfidence.ASPIRATIONAL: 0,
    ClaimConfidence.DESIGN_INTENT: 1,
    ClaimConfidence.VALIDATED_INTERNAL: 2,
    ClaimConfidence.VALIDATED_EXTERNAL: 3,
}


# ---------------------------------------------------------------------------
# Core dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScoredAssumption:
    assumption_id:      int
    claim:              str
    architect:          str
    base_score:         float       # raw impact score from Claude (1–10, normalised 0–1)
    claim_confidence:   ClaimConfidence
    specificity_score:  float       # 0.0–1.0
    adjusted_score:     float       # base × confidence_multiplier
    contradiction_flag: bool        # True = hard contradiction detected on this claim


# ---------------------------------------------------------------------------
# Specificity rule tables
# Each architect maps score bands (float) to a human-readable description
# of what earns that band.  Score is awarded by _score_specificity().
# ---------------------------------------------------------------------------

SPECIFICITY_RULES: dict[str, dict[float, str]] = {
    "PricingArchitect": {
        1.0: "contains exact ₹ amount AND billing frequency",
        0.6: "contains ₹ amount OR billing model, not both",
        0.2: "pricing category words only (affordable, competitive, freemium, premium)",
        0.0: "no pricing information",
    },
    "OnboardingArchitect": {
        1.0: "specific step count AND time measurement (3 steps, under 2 minutes, tested with N users)",
        0.6: "time OR step count but not both",
        0.2: "quality adjectives only (seamless, simple, easy, intuitive, frictionless)",
        0.0: "no onboarding description",
    },
    "TrustArchitect": {
        1.0: "specific review count OR named certifications OR named press mentions",
        0.6: "review count range OR certification category",
        0.2: "trust quality words only (trusted, established, known)",
        0.0: "no trust signal described",
    },
    "PerformanceThresholdArchitect": {
        1.0: "specific metric with unit (99.9% uptime, <200ms response, 48hr battery)",
        0.6: "relative performance claim with comparison (faster than X, better battery than Y)",
        0.2: "absolute quality words only (fast, reliable, accurate)",
        0.0: "no performance claim",
    },
    "RetentionArchitect": {
        1.0: "specific retention percentage with timeframe (45% day-7 retention, 3 of 10 returned)",
        0.6: "qualitative retention claim with mechanism (users come back because of X feature)",
        0.2: "general stickiness language (addictive, users love it, great engagement)",
        0.0: "no retention claim",
    },
    "CompetitiveDynamicsArchitect": {
        1.0: "named competitor + specific differentiation",
        0.6: "competitor category mentioned + differentiation",
        0.2: "differentiation claim without competitor reference",
        0.0: "no competitive context",
    },
    "MarketSizeArchitect": {
        1.0: "specific TAM/SAM/SOM with source citation or methodology",
        0.6: "market size estimate without citation",
        0.2: "market size qualitative only (large, growing, underserved)",
        0.0: "no market size claim",
    },
    "ChannelArchitect": {
        1.0: "specific channel with measured CAC or conversion rate",
        0.6: "specific channel named without cost data",
        0.2: "channel category only (digital, social, referral)",
        0.0: "no channel described",
    },
    "ProductValueArchitect": {
        1.0: "specific outcome with measurable unit (saves 2hr/week, reduces cost by 30%)",
        0.6: "benefit with direction but not quantified (saves time, reduces cost)",
        0.2: "generic value words only (better, faster, easier)",
        0.0: "no value claim",
    },
    "UnitEconomicsArchitect": {
        1.0: "specific LTV, CAC, or payback period with numbers",
        0.6: "one of LTV / CAC / payback mentioned without the others",
        0.2: "unit-economics vocabulary without numbers (profitable, sustainable)",
        0.0: "no unit-economics claim",
    },
    "RegulatoryArchitect": {
        1.0: "specific regulation named AND compliance status",
        0.6: "regulation domain mentioned without specific act/rule",
        0.2: "compliance language only (compliant, regulated, licensed)",
        0.0: "no regulatory claim",
    },
    "TeamCapabilityArchitect": {
        1.0: "named experience with specific prior outcome (built X at Y, exited Z)",
        0.6: "domain experience claimed with years or company name",
        0.2: "capability adjectives only (experienced, skilled, passionate)",
        0.0: "no team claim",
    },
    "SupplyChainArchitect": {
        1.0: "named supplier + lead time + margin",
        0.6: "named supplier or lead time but not both",
        0.2: "supply description without specifics (reliable, established supply)",
        0.0: "no supply chain information",
    },
    "NetworkEffectArchitect": {
        1.0: "specific network effect mechanism with measured or observed data",
        0.6: "network effect described with mechanism but unmeasured",
        0.2: "network effect claimed without mechanism (viral, network effects)",
        0.0: "no network effect claim",
    },
    "CustomerAcquisitionArchitect": {
        1.0: "specific acquisition experiment result (A/B test, paid campaign ROAS)",
        0.6: "acquisition channel tested but without controlled data",
        0.2: "acquisition plan without any test data",
        0.0: "no acquisition strategy described",
    },
}

_DEFAULT_SPECIFICITY = 0.5   # fallback for architects not in the table


# ---------------------------------------------------------------------------
# Confidence classification — heuristic keyword matching
# ---------------------------------------------------------------------------

_VALIDATED_EXTERNAL_SIGNALS = [
    r"\d+\s*users?\s*(?:tested|surveyed|interviewed)",
    r"market research",
    r"industry report",
    r"published study",
    r"according to",
    r"third.?party",
    r"external validation",
    r"cited",
    r"peer.?reviewed",
    r"data shows",
    r"research shows",
]

_VALIDATED_INTERNAL_SIGNALS = [
    r"we tested",
    r"we ran",
    r"we surveyed",
    r"beta test",
    r"pilot",
    r"prototype test",
    r"user interview",
    r"internal test",
    r"a/b test",
    r"waitlist",
    r"early adopter",
    r"measured",
    r"\d+ of \d+",
]

_ASPIRATIONAL_SIGNALS = [
    r"\bwill\b",
    r"\bplan to\b",
    r"\baim to\b",
    r"\bintend to\b",
    r"\bhope to\b",
    r"\bbelieve\b",
    r"\bexpect\b",
    r"\bshould\b",
    r"\bgoal\b",
    r"\bwant to\b",
    r"\bgoing to\b",
]


def classify_confidence(claim: str) -> ClaimConfidence:
    """
    Lightweight heuristic confidence classification.
    Checked in priority order: VALIDATED_EXTERNAL > VALIDATED_INTERNAL >
    ASPIRATIONAL > DESIGN_INTENT (default).
    """
    lower = claim.lower()
    for pattern in _VALIDATED_EXTERNAL_SIGNALS:
        if re.search(pattern, lower):
            return ClaimConfidence.VALIDATED_EXTERNAL

    for pattern in _VALIDATED_INTERNAL_SIGNALS:
        if re.search(pattern, lower):
            return ClaimConfidence.VALIDATED_INTERNAL

    for pattern in _ASPIRATIONAL_SIGNALS:
        if re.search(pattern, lower):
            return ClaimConfidence.ASPIRATIONAL

    return ClaimConfidence.DESIGN_INTENT


# ---------------------------------------------------------------------------
# Specificity scoring
# ---------------------------------------------------------------------------

_PRICING_AMOUNT_RE   = re.compile(r"[₹$€£]\s*[\d,]+|[\d,]+\s*(?:rupees?|inr|usd)", re.I)
_PRICING_FREQ_RE     = re.compile(r"per month|monthly|annual|yearly|one.?time|subscription|per user", re.I)
_PRICING_CATEGORY_RE = re.compile(r"\b(?:affordable|competitive|freemium|premium|free tier|pricing)\b", re.I)

_STEP_COUNT_RE = re.compile(r"\d+\s*steps?", re.I)
_TIME_RE       = re.compile(r"\d+\s*(?:second|minute|min|hour|sec)", re.I)
_QUALITY_RE    = re.compile(r"\b(?:seamless|simple|easy|intuitive|frictionless|smooth)\b", re.I)

_REVIEW_COUNT_RE = re.compile(r"\d+\s*(?:reviews?|ratings?|testimonials?)", re.I)
_CERT_RE         = re.compile(r"\b(?:iso|gdpr|hipaa|soc ?2|pci|rbi|sebi|fda|cert-in)\b", re.I)
_PRESS_RE        = re.compile(r"\b(?:featured in|mentioned in|covered by|press|techcrunch|yourstory|inc42)\b", re.I)
_TRUST_QUAL_RE   = re.compile(r"\b(?:trusted|established|known|reputable|reliable brand)\b", re.I)

_METRIC_UNIT_RE = re.compile(
    r"\d+\.?\d*\s*%\s*(?:uptime|accuracy|availability)|"
    r"<\s*\d+\s*ms|"
    r"\d+\s*(?:hr|hour|day)\s*battery",
    re.I,
)
_COMPARE_RE  = re.compile(r"(?:faster|better|more reliable|cheaper)\s+than\b", re.I)
_PERF_QUAL_RE = re.compile(r"\b(?:fast|reliable|accurate|performant|low.?latency)\b", re.I)

_RETENTION_PCT_RE = re.compile(
    r"\d+\s*%.*?(?:day.?\d+|week|month|retention|return)",
    re.I,
)
_RETENTION_RATIO_RE = re.compile(r"\d+\s*(?:of|out of)\s*\d+\s*(?:users?|customers?)?.*?return", re.I)
_RETENTION_MECH_RE  = re.compile(r"(?:come back|return)\s+because\s+of\b", re.I)
_STICKY_RE          = re.compile(r"\b(?:addictive|sticky|love it|engagement|habit.?forming)\b", re.I)

_NAMED_COMP_RE    = re.compile(r"(?:vs\.?|versus|compared to|unlike|better than)\s+[A-Z][a-z]+", re.I)
_COMP_CAT_RE      = re.compile(r"\b(?:competitor|alternative|incumbent|substitute|rival)\b", re.I)
_DIFFER_RE        = re.compile(r"\b(?:unique|differentiat|superior|advantage|unlike others)\b", re.I)


def _score_specificity(architect: str, claim: str) -> float:
    """
    Returns a specificity score in {0.0, 0.2, 0.6, 1.0} for known architects,
    or _DEFAULT_SPECIFICITY for unknown ones.
    """
    if architect not in SPECIFICITY_RULES:
        return _DEFAULT_SPECIFICITY

    lower = claim.lower()

    if architect == "PricingArchitect":
        has_amount = bool(_PRICING_AMOUNT_RE.search(claim))
        has_freq   = bool(_PRICING_FREQ_RE.search(lower))
        if has_amount and has_freq:
            return 1.0
        if has_amount or has_freq:
            return 0.6
        if _PRICING_CATEGORY_RE.search(lower):
            return 0.2
        return 0.0

    if architect == "OnboardingArchitect":
        has_steps = bool(_STEP_COUNT_RE.search(lower))
        has_time  = bool(_TIME_RE.search(lower))
        if has_steps and has_time:
            return 1.0
        if has_steps or has_time:
            return 0.6
        if _QUALITY_RE.search(lower):
            return 0.2
        return 0.0

    if architect == "TrustArchitect":
        if _REVIEW_COUNT_RE.search(lower) or _CERT_RE.search(lower) or _PRESS_RE.search(claim):
            return 1.0
        if re.search(r"\d+", lower) and _CERT_RE.search(lower):
            return 0.6
        if _TRUST_QUAL_RE.search(lower):
            return 0.2
        return 0.0

    if architect == "PerformanceThresholdArchitect":
        if _METRIC_UNIT_RE.search(claim):
            return 1.0
        if _COMPARE_RE.search(lower):
            return 0.6
        if _PERF_QUAL_RE.search(lower):
            return 0.2
        return 0.0

    if architect == "RetentionArchitect":
        if _RETENTION_PCT_RE.search(lower) or _RETENTION_RATIO_RE.search(lower):
            return 1.0
        if _RETENTION_MECH_RE.search(lower):
            return 0.6
        if _STICKY_RE.search(lower):
            return 0.2
        return 0.0

    if architect == "CompetitiveDynamicsArchitect":
        if _NAMED_COMP_RE.search(claim) and _DIFFER_RE.search(lower):
            return 1.0
        if _COMP_CAT_RE.search(lower) and _DIFFER_RE.search(lower):
            return 0.6
        if _DIFFER_RE.search(lower):
            return 0.2
        return 0.0

    # Generic fallback for architects in the rule table but without
    # bespoke regex (MarketSize, Channel, ProductValue, etc.)
    # Score 0.6 if claim contains any number, 0.2 otherwise.
    if re.search(r"\d", claim):
        return 0.6
    return 0.2


# ---------------------------------------------------------------------------
# Hard / soft contradiction detection
# ---------------------------------------------------------------------------

_HARD_CONTRADICTION_RULES: list[tuple[str, str, str]] = [
    ("free product",           "subscription revenue",   "free + subscription"),
    ("physical hardware",      "software only",          "hw + sw-only"),
    ("b2c consumer",           "enterprise procurement", "b2c + enterprise"),
    ("no data collected",      "personalisation feature","privacy + personalization"),
    ("offline only",           "cloud sync",             "offline + cloud"),
]

SOFT_CONTRADICTION_RULES: list[tuple[str, str]] = [
    ("premium pricing",       "tier-3 primary market"),
    ("simple product",        "extensive feature list"),
    ("freemium model",        "high cac tolerance"),
]


def _both_present(claims_lower: list[str], pattern_a: str, pattern_b: str) -> bool:
    has_a = any(pattern_a in c for c in claims_lower)
    has_b = any(pattern_b in c for c in claims_lower)
    return has_a and has_b


def detect_contradictions(
    assumptions: list[str],
) -> tuple[int, list[str]]:
    """
    Returns (hard_contradiction_count, soft_flags).

    hard_contradiction_count contributes a penalty to signal quality.
    soft_flags are returned to the frontend as clarifying questions.
    """
    lower = [a.lower() for a in assumptions]
    hard_count = 0
    for rule in _HARD_CONTRADICTION_RULES:
        if _both_present(lower, rule[0], rule[1]):
            hard_count += 1

    soft_flags: list[str] = []
    for rule in SOFT_CONTRADICTION_RULES:
        if _both_present(lower, rule[0], rule[1]):
            soft_flags.append(f"Consider clarifying: '{rule[0]}' alongside '{rule[1]}'")

    return hard_count, soft_flags


# ---------------------------------------------------------------------------
# Signal quality computation
# ---------------------------------------------------------------------------

def compute_signal_quality(
    scored_assumptions: list[ScoredAssumption],
    hard_contradiction_count: int,
) -> float:
    """
    Returns a float in [0.0, 1.0].

    Tiers:
      >= 0.50 → FULL      weight = signal_quality,       effective_count += 1.0
      0.25–0.49 → PARTIAL weight = signal_quality × 0.5, effective_count += 0.3
      < 0.25  → QUARANTINED weight = 0.0,                effective_count += 0.0
    """
    if not scored_assumptions:
        return 0.0

    validated_external_count = sum(
        1 for a in scored_assumptions
        if a.claim_confidence == ClaimConfidence.VALIDATED_EXTERNAL
    )
    validated_ratio  = validated_external_count / len(scored_assumptions)
    mean_specificity = sum(a.specificity_score for a in scored_assumptions) / len(scored_assumptions)

    raw = (
        validated_ratio  * 0.50
        + mean_specificity * 0.35
        - hard_contradiction_count * 0.12
    )
    return max(0.0, min(1.0, raw))


def signal_quality_tier(signal_quality: float) -> str:
    if signal_quality >= 0.50:
        return "FULL"
    if signal_quality >= 0.25:
        return "PARTIAL"
    return "QUARANTINED"


# ---------------------------------------------------------------------------
# High-level scorer — entry point called from the endpoint
# ---------------------------------------------------------------------------

def score_assumptions(
    assumptions: list[dict],
) -> tuple[list[ScoredAssumption], int, list[str], float]:
    """
    Args:
        assumptions: list of dicts with keys:
            id, text, category (used as architect name), impact_score

    Returns:
        (scored_list, hard_contradiction_count, soft_flags, signal_quality)
    """
    all_texts  = [a.get("text", "") for a in assumptions]
    hard_count, soft_flags = detect_contradictions(all_texts)

    scored: list[ScoredAssumption] = []
    for a in assumptions:
        claim     = a.get("text", "")
        architect = a.get("category", "General")
        raw_score = float(a.get("impact_score", 5.0))
        # Normalise impact score from 1–10 range to 0–1
        base_score = max(0.0, min(1.0, (raw_score - 1.0) / 9.0))

        confidence = classify_confidence(claim)
        extra_raw = a.get("claim_confidence")
        if extra_raw is not None and str(extra_raw).strip() != "":
            try:
                c_extra = ClaimConfidence(str(extra_raw).strip().upper().replace(" ", "_"))
            except ValueError:
                c_extra = None
            if c_extra is not None and _CONFIDENCE_RANK.get(c_extra, 0) > _CONFIDENCE_RANK.get(
                confidence, 0
            ):
                confidence = c_extra
        multiplier   = CONFIDENCE_MULTIPLIERS[confidence]
        specificity  = _score_specificity(architect, claim)
        adjusted     = base_score * multiplier

        scored.append(
            ScoredAssumption(
                assumption_id=int(a.get("id", 0)),
                claim=claim,
                architect=architect,
                base_score=base_score,
                claim_confidence=confidence,
                specificity_score=specificity,
                adjusted_score=adjusted,
                contradiction_flag=False,  # per-claim flagging not yet implemented
            )
        )

    sq = compute_signal_quality(scored, hard_count)
    return scored, hard_count, soft_flags, sq
