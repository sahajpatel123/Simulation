"""
AISkepticismArchitect — consumer skepticism about AI-powered offers.

Why it exists
-------------
TheCee models trust, price, retention, execution capability and regulatory
exposure, but nothing in the live funnel accounts for the fastest-growing
consumer failure mode of the current generation of pitches: the product is
an AI product, and the consumer does not believe it is safe, accurate or
respectful of their data. A brief that leads with "fully automated, no
humans, trained on your data" converts poorly with risk-averse and low-trust
clusters, while a brief that names human fallback, explainability and
data-control opt-outs earns the benefit of the doubt even from skeptics.

What this architect does
------------------------
* **Signal extraction** — reads the project description plus scored
  assumption texts and scores three evidence classes:
  - *AI presence*: explicit AI vocabulary (AI, machine learning, LLM,
    chatbot, copilot, automation, recommendation engine, ...). Detection is
    negation-aware, so "no AI", "AI-free" and "not an AI product" are never
    read as AI presence, while "not just an AI assistant" still is.
  - *risk exposure*: automation/opacity ("fully automated", "no human
    oversight"), hallucination/accuracy ("hallucination", "made up
    answers"), data misuse ("trained on your data", "microphone",
    "biometric") and displacement anxiety ("replaces jobs", "no human
    touch"). Phrases such as "no human review" are gaps, never proof.
  - *trust mitigations*: human fallback ("human in the loop", "escalate
    to a human"), transparency ("explainability", "fact-checked",
    "third-party audit", "confidence score") and data controls ("opt-out",
    "on-device", "does not train on your data", "privacy policy").
    Mitigations are negation-aware too: "no human review" cannot be both
    a risk signal and a mitigation.
* **Skepticism modelling** — combines per-cluster traits (low trust, high
  risk aversion, low digital literacy, low patience) with demographic age
  and product stakes (health/enterprise/B2B products carry higher downside
  if the AI is wrong) into a 0-1 skepticism score.
* **Funnel suppression** — when AI risk is perceived and mitigations are
  weak, consumers hesitate at the DECIDE stage, so DECIDE→PURCHASE is
  suppressed. When the brief never mentions AI at all, the funnel stays
  neutral (mirroring RunwayArchitect and FounderExecutionArchitect).
* **Founder insight** — the cross-cluster report names which segments stop
  short because the offer looks like an unaccountable black box and tells
  the founder exactly which mitigation class (human fallback,
  transparency, data control) is missing.

Pure compute — no I/O, no DB, no LLM, no randomness.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from app.simulation.architects.base import (
    ArchitectOutput,
    BaseArchitect,
    DomainReport,
)
from app.simulation.clusters.definitions import ClusterDefinition

# ── Model constants ─────────────────────────────────────────────────────

_ACTIVE_TRUST_GAP_THRESHOLD: float = 0.25
_CRITICAL_TRUST_GAP_THRESHOLD: float = 0.55
_SUPPRESSOR_FLOOR: float = 0.55
_RISK_WEIGHT_ON_GAP: float = 0.62
_MITIGATION_EFFECTIVENESS: float = 0.85

_HIGH_STAKE_PRODUCT_TYPES: frozenset[str] = frozenset({
    "health_hardware", "enterprise_software", "b2b_hardware",
    "b2b_marketplace", "iot_hardware", "wearable",
})


# ── AI presence vocabulary ──────────────────────────────────────────────

# Ordered longest-first so "ai chatbot" wins over bare "ai" at the same
# span and phrase-level matches are not shadowed by their components.
_AI_PRESENCE_KEYWORDS: tuple[str, ...] = (
    "artificial intelligence", "machine learning", "large language model",
    "generative ai", "deep learning", "neural network", "computer vision",
    "natural language processing", "predictive analytics",
    "predictive model", "recommendation engine", "personalization engine",
    "voice assistant", "smart assistant", "virtual assistant",
    "ai assistant", "ai agent", "autonomous agent", "ai-powered",
    "ai power", "ai model", "ai chatbot", "face recognition",
    "voice recognition", "speech recognition", "object detection",
    "image generation", "text generation", "content generation",
    "summarization", "document understanding", "self-driving",
    "chatbot", "chat bot", "copilot", "gpt", "chatgpt",
    "fully automated", "fully automatic", "automated decision",
    "automated decisions", "automation", "automated", "autonomous",
    "algorithmic", "algorithm", "intelligent", "llm", "nlp",
    "ai", "a.i.",
)

# Phrases that explicitly deny AI presence. Matches overlapping one of
# these are never counted as AI presence.
_PRESENCE_EXCLUSION_PATTERN = re.compile(
    r"\b(?:ai|a\.i\.|algorithm|automation|chatbot|llm)\s*[- ]?free\b"
    r"|\b(?:no|not|without|never)\s+(?:ai|a\.i\.|chatbot|automation)\b",
    re.IGNORECASE,
)


# ── AI risk-exposure vocabulary ─────────────────────────────────────────

# Self-negated phrases ("no human oversight") are the signal itself and
# must not be voided by the generic negation scanner. Ordered longest-first
# so the full phrase wins over a shorter prefix.
_RISK_AUTOMATION_KEYWORDS: tuple[str, ...] = (
    "no human involvement", "no human oversight", "no human fallback",
    "no human review", "no human support", "without human oversight",
    "without human fallback", "without human review",
    "automated decision", "automated decisions", "auto-approval",
    "auto approval", "algorithm decides", "ai decides",
    "fully automated", "fully automatic", "automated support",
    "no humans", "no human", "without human", "human-free",
    "human free", "self-driving", "autonomous", "chatbot only",
)

_RISK_HALLUCINATION_KEYWORDS: tuple[str, ...] = (
    "hallucination", "hallucinations", "hallucinate", "hallucinated",
    "hallucinates", "fabricated", "misinformation", "false information",
    "wrong answers", "made up answers", "confidently wrong",
    "inaccurate", "deepfake",
)

_RISK_DATA_KEYWORDS: tuple[str, ...] = (
    "trained on your data", "trains on your data", "train on your data",
    "train on user data", "uses your data", "use your data",
    "collects data", "collects personal data", "data collection",
    "scans your", "records audio", "location data", "health data",
    "shares data", "share your data", "sells data", "sell your data",
    "third party", "third parties", "targeted ads", "monitors",
    "records", "camera", "microphone", "biometric", "tracking",
    "tracks you", "cookies", "advertising",
)

_RISK_DISPLACEMENT_KEYWORDS: tuple[str, ...] = (
    "replaces jobs", "replace employees", "replace workers",
    "replaces human", "eliminates jobs", "job losses", "layoffs",
    "no human touch", "without human touch", "impersonal",
)

_RISK_SELF_NEGATED: frozenset[str] = frozenset({
    "no human involvement", "no human oversight", "no human fallback",
    "no human review", "no human support", "without human oversight",
    "without human fallback", "without human review", "no humans",
    "no human", "without human", "human-free", "human free",
    "no human touch", "without human touch",
})

# "camera-free" / "microphone-free" products are privacy positives, not
# data-collection risks. Spans overlapping these never count as risk.
_RISK_EXCLUSION_PATTERN = re.compile(
    r"\b(?:camera|microphone|tracking)-?free\b"
    r"|\b(?:records?|tracks?|monitors?)\s+"
    r"(?:no|not|nothing|none|never)\b",
    re.IGNORECASE,
)


# ── AI trust-mitigation vocabulary ──────────────────────────────────────

_MITIGATION_HUMAN_KEYWORDS: tuple[str, ...] = (
    "human in the loop", "human-in-the-loop", "human in loop",
    "human review", "human approval", "human oversight",
    "human agent", "human expert", "talk to a human",
    "speak to a human", "reach a human", "human support",
    "escalate to a human", "escalation path", "manual review",
    "human check", "human override", "human confirmation",
    "human team", "fallback to human", "human fallback",
)

_MITIGATION_TRANSPARENCY_KEYWORDS: tuple[str, ...] = (
    "explains its reasoning", "shows its work", "explainability",
    "explainable", "confidence score", "confidence scores",
    "cited sources", "source citations", "fact-checked",
    "fact checking", "fact-check", "fact check", "third-party audit",
    "third party audit", "red team", "red-teamed", "red teaming",
    "bias testing", "bias test", "verification", "verified",
    "transparent", "transparency", "citations", "audit", "audited",
    "guardrails", "fairness", "alignment", "accuracy rate",
    "benchmark",
)

_MITIGATION_DATA_KEYWORDS: tuple[str, ...] = (
    "delete your data", "data deletion", "privacy by design",
    "data minimisation", "data minimization", "does not train",
    "do not train", "no training on", "not trained on",
    "does not store", "do not store", "opt-out of ai", "opt-out",
    "opt out", "privacy policy", "consent", "encryption",
    "on-device", "on device", "local processing", "local model",
    "offline mode", "anonymised", "anonymized",
)

# "human review no longer offered" / "opt-out not available" are gaps, not
# mitigations. Matches overlapping these never count as mitigation.
_MITIGATION_EXCLUSION_PATTERN = re.compile(
    r"\b(?:human review|human support|human fallback|human oversight|"
    r"fact-?checked|opt-?out|on-?device|encryption|consent)\s+"
    r"(?:no|not|never|nothing|none|without)\b",
    re.IGNORECASE,
)


# ── Text helpers ────────────────────────────────────────────────────────

_CONTRACTION_SUFFIXES: dict[str, str] = {
    "isn": "is not", "aren": "are not", "wasn": "was not",
    "weren": "were not", "don": "do not", "doesn": "does not",
    "didn": "did not", "haven": "have not", "hasn": "has not",
    "hadn": "had not", "won": "will not", "wouldn": "would not",
    "can": "cannot", "couldn": "could not", "shouldn": "should not",
    "mustn": "must not", "needn": "need not", "ain": "is not",
}
_CONTRACTION_PATTERN = re.compile(
    r"\b((?:isn|aren|wasn|weren|don|doesn|didn|haven|hasn|hadn|won|"
    r"wouldn|can|couldn|shouldn|mustn|needn|ain))'?t\b"
)
_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[.,;:!?—–\n]|\b(?:but|yet|though|although|whereas|however|while|"
    r"and|or)\b",
    re.IGNORECASE,
)
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks",
    "lacking", "missing", "absent", "absence", "unclear", "uncertain",
    "unknown", "unverified", "unconfirmed", "pending", "awaiting",
    "void", "none", "nothing", "neither", "nor",
})
_DISCOURSE_FOCUS: frozenset[str] = frozenset({
    "just", "only", "merely", "simply",
})


@lru_cache(maxsize=32)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _normalise(text: str) -> str:
    """Lowercase and expand common contracted negations."""
    lowered = text.lower()
    return _CONTRACTION_PATTERN.sub(
        lambda m: _CONTRACTION_SUFFIXES[m.group(1)], lowered
    )


def _trait(traits: dict[str, Any], key: str, default: float = 0.5) -> float:
    """Parse one trait value, falling back to ``default`` on garbage input."""
    value = traits.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _collect_texts(
    assumptions: list[dict[str, Any]] | None,
    env_params: dict[str, Any] | None,
) -> list[str]:
    """Gather pitch texts: scored assumptions plus project description.

    Null or blank entries are not evidence, and identical texts are
    de-duplicated so the same claim repeated in an assumption and the
    description is not counted multiple times.
    """
    texts: list[str] = []
    for assumption in assumptions or []:
        if isinstance(assumption, dict):
            raw = assumption.get("text", assumption.get("assumption", ""))
        else:
            raw = assumption
        if raw is None:
            continue
        raw = str(raw)
        if not raw.strip():
            continue
        texts.append(_normalise(raw))
    description = (env_params or {}).get("description", "")
    if description is not None:
        description = str(description).strip()
        if description:
            texts.append(_normalise(description))
    return list(dict.fromkeys(texts))


def _is_discourse_negation(window: list[str]) -> bool:
    """True for "not just"/"not only" focus constructions."""
    return any(
        window[i] == "not"
        and i + 1 < len(window)
        and window[i + 1] in _DISCOURSE_FOCUS
        for i in range(len(window) - 1)
    )


def _is_voided(
    text: str,
    start: int,
    end: int,
    *,
    self_negated: bool = False,
    check_trailing: bool = False,
) -> bool:
    """True when a negation marker scopes onto a keyword match.

    ``self_negated`` phrases ("no human oversight") are the signal itself
    and are never voided. "not just AI" is a focus construction and is
    intentionally not treated as a negation.
    """
    if self_negated:
        return False
    boundaries_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = boundaries_before[-1].end() if boundaries_before else 0
    window = re.findall(r"[a-z]+", text[clause_start:start])[-4:]
    if _is_discourse_negation(window):
        return False
    if set(window) & _NEGATION_MARKERS:
        return True
    if check_trailing:
        boundaries_after = list(
            _CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text))
        )
        clause_end = (
            boundaries_after[0].start() if boundaries_after else len(text)
        )
        trailing = re.findall(r"[a-z]+", text[end:clause_end])[:3]
        if set(trailing) & _NEGATION_MARKERS:
            return True
    return False


def _count_matches(
    text: str,
    keywords: tuple[str, ...],
    *,
    self_negated: frozenset[str] = frozenset(),
    exclusion_pattern: re.Pattern[str] | None = None,
    check_trailing: bool = False,
) -> int:
    """Count unvoided keyword matches, honouring self-negated phrases."""
    excluded = (
        [match.span() for match in exclusion_pattern.finditer(text)]
        if exclusion_pattern is not None
        else []
    )
    pattern = _keyword_pattern(keywords)
    count = 0
    for match in pattern.finditer(text):
        matched = text[match.start():match.end()].lower()
        if any(s <= match.start() and match.end() <= e for s, e in excluded):
            continue
        if _is_voided(
            text,
            match.start(),
            match.end(),
            self_negated=matched in self_negated,
            check_trailing=check_trailing,
        ):
            continue
        count += 1
    return count


# ── Model helpers ───────────────────────────────────────────────────────


def _age_factor(age_bracket: str) -> float:
    """Small demographic adjustment to AI skepticism from age brackets."""
    ages = [int(value) for value in re.findall(r"\d+", str(age_bracket or ""))]
    if not ages:
        return 0.0
    lower, upper = min(ages), max(ages)
    if lower >= 45 or upper >= 60:
        return 0.08
    if upper <= 24:
        return -0.06
    if upper >= 50:
        return 0.04
    return 0.0


def _ai_skepticism(
    traits: dict[str, Any],
    age_bracket: str,
    product_type: str,
) -> float:
    """Per-cluster skepticism toward AI-powered offers."""
    trust = _trait(traits, "trust")
    risk_aversion = _trait(traits, "risk_aversion")
    literacy = _trait(traits, "digital_literacy")
    patience = _trait(traits, "patience_score")
    stakes = 0.10 if product_type in _HIGH_STAKE_PRODUCT_TYPES else 0.0
    return _clamp(
        0.18
        + (1.0 - trust) * 0.34
        + risk_aversion * 0.22
        + (1.0 - literacy) * 0.16
        + (1.0 - patience) * 0.08
        + _age_factor(age_bracket)
        + stakes,
        low=0.15,
        high=0.95,
    )


def _mitigation_credibility(counts: dict[str, int]) -> float:
    """Coverage of the three mitigation classes (0.0 / 0.30 / 0.60 / 0.90)."""
    covered = sum(1 for count in counts.values() if count > 0)
    return {0: 0.0, 1: 0.30, 2: 0.60, 3: 0.90}[covered]


def _risk_load(covered_groups: int, signal_count: int) -> float:
    """AI risk exposure from the brief: groups matter more than repetition."""
    return _clamp(
        0.35
        + 0.15 * covered_groups
        + 0.05 * min(signal_count, 4),
        low=0.35,
        high=1.0,
    )


class AISkepticismArchitect(BaseArchitect):
    """Evaluates consumer skepticism toward AI-powered offers."""

    @property
    def name(self) -> str:
        return "AISkepticismArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Any pitch can lead with AI, so the domain is universal.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        product_type = str(env_params.get("product_type", "saas")).lower()
        age_bracket = str(
            (cluster.demographic_profile or {}).get("age_bracket", "")
        )

        texts = _collect_texts(assumptions, env_params)
        joined = "\n".join(texts)
        presence = _count_matches(
            joined,
            _AI_PRESENCE_KEYWORDS,
            exclusion_pattern=_PRESENCE_EXCLUSION_PATTERN,
        )
        ai_present = presence > 0

        if not ai_present:
            return ArchitectOutput(
                architect_name=self.name,
                cluster_id=cluster.cluster_id,
                metrics={
                    "ai_presence_score": 0.0,
                    "ai_risk_load": 0.0,
                    "ai_skepticism": 0.0,
                    # No AI in the pitch means nothing to mitigate: report
                    # full credibility so accountability stays quiet.
                    "ai_mitigation_credibility": 1.0,
                    "perceived_ai_risk": 0.0,
                    "ai_trust_gap": 0.0,
                    "ai_funnel_suppressor": 1.0,
                },
                flags={
                    "ai_powered_offer": False,
                    "ai_trust_gap_active": False,
                    "automation_opacity_risk": False,
                    "hallucination_risk": False,
                    "data_misuse_concern": False,
                    "displacement_anxiety_risk": False,
                    "human_fallback_present": False,
                    "ai_transparency_present": False,
                    "data_control_mitigation_present": False,
                },
                narrative_findings=[
                    "AI skepticism neutral: pitch does not mention AI",
                ],
                severity="INFO",
            )

        skepticism = _ai_skepticism(traits, age_bracket, product_type)

        risk_counts = {
            "automation": _count_matches(
                joined,
                _RISK_AUTOMATION_KEYWORDS,
                self_negated=_RISK_SELF_NEGATED,
            ),
            "hallucination": _count_matches(
                joined,
                _RISK_HALLUCINATION_KEYWORDS,
            ),
            "data": _count_matches(
                joined,
                _RISK_DATA_KEYWORDS,
                exclusion_pattern=_RISK_EXCLUSION_PATTERN,
            ),
            "displacement": _count_matches(
                joined,
                _RISK_DISPLACEMENT_KEYWORDS,
                self_negated=_RISK_SELF_NEGATED,
            ),
        }
        covered_risk_groups = sum(1 for count in risk_counts.values() if count > 0)
        risk_signal_count = sum(min(count, 2) for count in risk_counts.values())
        risk_load = _risk_load(covered_risk_groups, risk_signal_count)

        mitigation_counts = {
            "human": _count_matches(
                joined,
                _MITIGATION_HUMAN_KEYWORDS,
                exclusion_pattern=_MITIGATION_EXCLUSION_PATTERN,
                check_trailing=True,
            ),
            "transparency": _count_matches(
                joined,
                _MITIGATION_TRANSPARENCY_KEYWORDS,
                exclusion_pattern=_MITIGATION_EXCLUSION_PATTERN,
                check_trailing=True,
            ),
            "data": _count_matches(
                joined,
                _MITIGATION_DATA_KEYWORDS,
                exclusion_pattern=_MITIGATION_EXCLUSION_PATTERN,
                check_trailing=True,
            ),
        }
        credibility = _mitigation_credibility(mitigation_counts)

        perceived_risk = _clamp(skepticism * risk_load)
        trust_gap = _clamp(
            perceived_risk * (1.0 - credibility * _MITIGATION_EFFECTIVENESS)
        )
        active = trust_gap >= _ACTIVE_TRUST_GAP_THRESHOLD
        if active:
            suppressor = round(
                _clamp(
                    1.0 - trust_gap * _RISK_WEIGHT_ON_GAP,
                    low=_SUPPRESSOR_FLOOR,
                ),
                4,
            )
        else:
            suppressor = 1.0

        critical = active and (
            trust_gap >= _CRITICAL_TRUST_GAP_THRESHOLD
            or (
                covered_risk_groups >= 2
                and credibility == 0.0
                and risk_load >= 0.75
            )
        )
        severity = (
            "CRITICAL"
            if critical
            else "WARNING"
            if active
            else "INFO"
        )

        risk_labels = [
            label
            for label, count in risk_counts.items()
            if count > 0
        ]
        mitigation_labels = [
            label
            for label, count in mitigation_counts.items()
            if count > 0
        ]

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "ai_presence_score": round(
                    min(1.0, presence / 2.0), 4
                ),
                "ai_risk_load": round(risk_load, 4),
                "ai_skepticism": round(skepticism, 4),
                "ai_mitigation_credibility": round(credibility, 4),
                "perceived_ai_risk": round(perceived_risk, 4),
                "ai_trust_gap": round(trust_gap, 4),
                "ai_funnel_suppressor": suppressor,
            },
            flags={
                "ai_powered_offer": True,
                "ai_trust_gap_active": active,
                "automation_opacity_risk": risk_counts["automation"] > 0,
                "hallucination_risk": risk_counts["hallucination"] > 0,
                "data_misuse_concern": risk_counts["data"] > 0,
                "displacement_anxiety_risk": risk_counts["displacement"] > 0,
                "human_fallback_present": mitigation_counts["human"] > 0,
                "ai_transparency_present": mitigation_counts["transparency"] > 0,
                "data_control_mitigation_present": mitigation_counts["data"] > 0,
            },
            narrative_findings=[
                (
                    f"AI presence: {presence} signal(s) | "
                    f"Risk load: {risk_load:.2f} | "
                    f"Skepticism: {skepticism:.2f}"
                ),
                (
                    f"AI trust gap: {trust_gap:.2f} | "
                    f"Mitigation credibility: {credibility:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                ),
                (
                    f"Risks: {', '.join(risk_labels) or 'none'} | "
                    f"Mitigations: {', '.join(mitigation_labels) or 'none'}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("ai_funnel_suppressor", 1.0))
        if suppressor >= 1.0:
            return {}
        return {
            ("DECIDE", "PURCHASE"): max(
                _SUPPRESSOR_FLOOR,
                min(0.999, suppressor),
            ),
        }

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        critical = [
            output
            for output in outputs
            if output.flags.get("ai_trust_gap_active")
            and output.severity == "CRITICAL"
        ]
        active = [
            output
            for output in outputs
            if output.flags.get("ai_trust_gap_active")
        ]
        affected = list(
            dict.fromkeys(
                output.cluster_id
                for output in critical + active
                if output.cluster_id
            )
        )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters discount the offer on AI "
                f"trust; {len(active)} clusters show AI-skepticism "
                f"driven purchase drop-off"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(min(1.0, len(affected) * 0.03), 3),
            conversion_impact=round(
                len(critical) * 0.04
                + (len(active) - len(critical)) * 0.015,
                3,
            ),
            recommended_action=(
                "Publish AI trust evidence: human fallback or escalation "
                "path, explainability/fact-checking, and data-control "
                "opt-outs with an audit or accuracy benchmark"
            ),
            severity="CRITICAL" if critical else "WARNING" if active else "INFO",
        )


__all__ = ["AISkepticismArchitect"]
