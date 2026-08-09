"""
MessagingClarityArchitect — value-proposition comprehension founder insight.

Why it exists
-------------
TheCee models demand, price, trust, retention, supply chain and cash runway
across the 52 clusters, but nothing in the live funnel accounts for the
simplest failure mode: a consumer who cannot tell what the product is, who
it is for, or what outcome it delivers will never seriously consider it.
A pitch full of hype words ("AI-powered", "cutting-edge", "seamless
platform") can read as a red flag to skeptical consumers, and abstract
positioning is disproportionately costly for low-digital-literacy clusters.

What this architect does
------------------------
* **Signal extraction** — reads the project description plus the scored
  assumption texts and scores four concrete signals:
  - *category anchor*: does it name what the product is (CRM, tracker,
    marketplace, "is an app that ...")?
  - *audience specificity*: does it name who it is for ("for small
    businesses", "for runners") or both sides of a marketplace
    ("connecting designers with clients")?
  - *use-case specificity*: does it describe when/where it is used?
  - *outcome specificity*: does it state a quantified or directional
    outcome ("cuts follow-up time by 40%", "saves time")?
  It also measures *vague-language density* (hype adjectives and empty
  nouns such as "platform"/"solution").
* **Comprehension modelling** — combines the text-level clarity with
  per-cluster traits: low digital literacy, low motivation and low trust
  amplify comprehension risk, so the same pitch converts differently for
  a metro power professional than a tier-3 first-time app user.
* **Funnel suppression** — unclear messaging suppresses BROWSE→CONSIDER
  (consumers who cannot understand the offer do not move into
  consideration). For high-ticket products, where the final decision
  carries more risk, it also suppresses CONSIDER→DECIDE.
* **Founder insight** — the cross-cluster report names which segments
  drop out because the value proposition is hard to grasp and tells the
  founder exactly which signal is missing (audience, outcome, category,
  use case) and how to fix it.

The model is deliberately conservative: when the brief contains no
product/description/assumption text at all, nothing is penalised and the
funnel stays neutral (mirroring RunwayArchitect's "not discussed" rule).

Pure compute — no I/O, no DB, no LLM, no randomness.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

# ── Model constants ─────────────────────────────────────────────────────

_CLEAR_THRESHOLD: float = 0.75          # base clarity at/beyond which the
                                        # funnel is never suppressed
_SUPPRESSOR_FLOOR: float = 0.55
_DECISION_SUPPRESSOR_FLOOR: float = 0.45
_CRITICAL_CLARITY_THRESHOLD: float = 0.40
_HIGH_TICKET_AOV: float = 10_000.0


# ── Audience phrases (word-boundary, case-insensitive) ──────────────────

_AUDIENCE_KEYWORDS: tuple[str, ...] = (
    # B2B / professional
    "for small businesses", "for small business", "for smbs", "for smb",
    "for startups", "for start-ups", "for founders", "for entrepreneurs",
    "for developers", "for engineers", "for programmers", "for designers",
    "for creators", "for freelancers", "for agencies", "for teams",
    "for enterprises", "for companies", "for businesses", "for sme",
    "for smes", "for professionals", "for accountants", "for lawyers",
    "for consultants", "for sales teams", "for salespeople", "for hr",
    "for recruiters", "for marketers", "for operations",
    "for manufacturers", "for distributors", "for wholesalers",
    "for remote workers", "for hybrid teams", "for call centers",
    "for call centres", "for customer service", "for logistics",
    "for warehouse", "for fleet managers", "for field workers",
    "for technicians", "for electricians", "for plumbers",
    "for contractors",
    # Consumer
    "for retailers", "for restaurants", "for cafes", "for clinics",
    "for doctors", "for physicians", "for patients", "for hospitals",
    "for nurses", "for students", "for teachers", "for parents",
    "for families", "for children", "for kids", "for pet owners",
    "for travelers", "for travellers", "for tourists", "for drivers",
    "for commuters", "for riders", "for women", "for men", "for seniors",
    "for senior citizens", "for the elderly", "for farmers",
    "for gym goers", "for athletes", "for runners", "for cyclists",
    "for gamers", "for job seekers", "for homeowners", "for landlords",
    "for tenants", "for renters",
    # Targeting language
    "target audience", "target users", "target user", "target customers",
    "target customer", "target market", "intended for", "aimed at",
    "geared toward", "geared towards", "serves", "serving",
)

# Two-sided / bridge phrasing: "connecting designers with clients",
# "matches renters with landlords", "links students to tutors".
_AUDIENCE_BRIDGE_RE = re.compile(
    r"\b(?:connecting|connects|matches?|links?|bridges?)\s+"
    r"[a-z][a-z ]{1,24}?\s+(?:with|and|to)\s+[a-z][a-z ]{1,24}\b",
    re.IGNORECASE,
)


# ── Use-case phrases ────────────────────────────────────────────────────

_USE_CASE_KEYWORDS: tuple[str, ...] = (
    "use case", "use cases", "scenario", "scenarios",
    "when you", "when they", "when he", "when she", "when the user",
    "when a user", "while working", "while driving", "while traveling",
    "while travelling", "while commuting", "while studying", "while cooking",
    "while shopping", "while exercising", "while running", "while sleeping",
    "during workouts", "during meetings", "during calls", "during travel",
    "during commute", "during class", "during checkout", "during delivery",
    "at the gym", "at the office", "at work", "at home", "at the store",
    "at the checkout", "at the clinic", "at the hospital",
    "at the warehouse", "on the go", "on the road", "on a trip",
    "on holiday", "in the kitchen", "in the field", "in the classroom",
    "in the hospital", "in the warehouse", "in the store", "in the gym",
    "before bed", "after work", "after school", "after a workout",
    "during a workout", "before a workout",
    "for sleep", "for fitness", "for wellness", "for health",
    "for productivity", "for learning", "for studying", "for shopping",
    "for cooking", "for travel", "for finance", "for money", "for taxes",
    "for accounting", "for sales", "for marketing", "for hiring",
    "for recruiting", "for scheduling", "for bookings", "for daily use",
    "for everyday use", "for outdoor use", "for indoor use", "for home use",
    "for office use",
)


# ── Category anchors ────────────────────────────────────────────────────

_CATEGORY_NOUN_KEYWORDS: tuple[str, ...] = (
    "crm", "erp", "pos", "dashboard", "marketplace", "chatbot", "assistant",
    "sensor", "tracker", "smartwatch", "wearable", "monitor", "billing",
    "inventory", "booking", "payments", "payment", "analytics", "automation",
    "recruiting", "scheduling", "accounting", "tax", "insurance", "lending",
    "ecommerce", "e-commerce", "store", "social network", "community",
    "newsletter", "helpdesk", "knowledge base", "workflow",
    "project management", "task manager", "wallet", "food delivery",
    "grocery", "ride hailing", "fleet management", "cold chain",
    "logistics", "supply chain", "plugin", "extension", "cli", "sdk",
    "api", "robot", "drone", "speaker", "camera", "hub", "thermostat",
    "headphones", "glucose monitor", "blood pressure monitor",
    "health monitor", "fitness tracker", "smart plug", "website builder",
    "email marketing", "customer support", "saas", "mobile app",
    "web app", "hardware", "device", "gadget", "blood pressure",
    "heart rate", "sleep tracker", "activity tracker", "appointment",
    "invoicing", "payroll", "compliance", "security", "identity",
    "authentication", "messaging", "video calling", "calendar",
)

# "is a platform", "software for X", "an app that ..." — generic category
# words count as anchors only when they are structurally attached to a
# product statement, not when they float alone as hype nouns.
_CATEGORY_PHRASE_RE = re.compile(
    r"\b(?:is|be)\s+(?:a|an|the)\s+(?:saas|software|app|platform|tool|"
    r"device|hardware|service)\b"
    r"|\b(?:saas|software|app|tool|device|hardware|service)\s+for\b"
    r"|\b(?:app|tool|software|platform|device|service)\s+that\b",
    re.IGNORECASE,
)


# ── Vague / hype language ───────────────────────────────────────────────

_VAGUE_KEYWORDS: tuple[str, ...] = (
    "ai-powered", "ai powered", "ai-driven", "ai driven",
    "machine learning", "ml-powered", "ml powered",
    "innovative", "innovation", "revolutionary", "revolutionize",
    "revolutionise", "disruptive", "disrupting", "next-gen",
    "next generation", "cutting-edge", "cutting edge",
    "state of the art", "state-of-the-art", "world-class", "best-in-class",
    "industry-leading", "game-changing", "game changer", "paradigm",
    "paradigm shift", "synergy", "synergistic", "leverage",
    "seamless", "effortless", "frictionless", "powerful", "robust",
    "scalable", "enterprise-grade", "future-proof", "one-stop",
    "all-in-one", "comprehensive", "holistic", "sophisticated",
    "unmatched", "unparalleled", "unprecedented", "ultimate",
    "breakthrough", "pioneering", "platform", "solution", "solutions",
    "ecosystem", "suite",
)


# ── Concrete outcome patterns ───────────────────────────────────────────

_CONCRETE_NUMERIC_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|usd|inr|rs\.?|dollars?|rupees?|"
    r"₹|€|£|\$)"
    r"|\b\d+(?:\s*[-–])?\s*(?:minutes?|mins?|seconds?|secs?|hours?|hrs?|"
    r"days?|weeks?|months?)\b"
    r"|\b\d+\s*(?:users?|customers?|orders?|tickets?|leads?|tasks?|"
    r"documents?|files?|devices?|reports?|clicks?|conversions?|signups?|"
    r"requests?|emails?|calls?|meetings?|steps?|features?|products?|"
    r"countries?|cities?|stores?|clinics?|hospitals?)\b",
    re.IGNORECASE,
)

_OUTCOME_VERB_RE = re.compile(
    r"\b(?:saves?|cuts?|reduces?|improves?|increases?|boosts?|grows?|"
    r"lowers?|eliminates?|removes?|automates?|streamlines?|speeds? up|"
    r"frees? up|slashes?|halves?|doubles?|triples?)\b",
    re.IGNORECASE,
)


# ── Helpers ─────────────────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _normalise(text: str) -> str:
    """Lowercase for deterministic keyword matching."""
    return text.lower()


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _collect_texts(
    assumptions: list[dict[str, Any]] | None,
    env_params: dict[str, Any] | None,
) -> list[str]:
    """Gather the pitch texts: scored assumptions plus project description."""
    texts: list[str] = []
    for assumption in assumptions or []:
        if isinstance(assumption, dict):
            raw = str(assumption.get("text", assumption.get("assumption", "")))
        else:
            raw = str(assumption)
        if raw.strip():
            texts.append(_normalise(raw))
    description = str((env_params or {}).get("description", "")).strip()
    if description:
        texts.append(_normalise(description))
    return texts


def _signal_scores(texts: list[str]) -> dict[str, float]:
    """Derive text-level clarity signals, all deterministic and bounded."""
    if not texts:
        return {
            "evidence": 0.0,
            "base_clarity": 1.0,
            "outcome": 0.0,
            "audience": 0.0,
            "use_case": 0.0,
            "category": 0.0,
            "vague_density": 0.0,
            "buzz_hits": 0.0,
            "concrete_hits": 0.0,
        }

    joined = "\n".join(texts)
    numeric_hits = len(_CONCRETE_NUMERIC_RE.findall(joined))
    verb_hits = len(_OUTCOME_VERB_RE.findall(joined))
    concrete_hits = float(numeric_hits + verb_hits)

    # One quantified or directional outcome is strong evidence; the score
    # saturates around three outcome signals.
    outcome_hits = numeric_hits + verb_hits * 0.5
    outcome = _clamp(0.15 + 0.85 * min(1.0, outcome_hits * 0.6))

    audience_hits = len(_keyword_pattern(_AUDIENCE_KEYWORDS).findall(joined))
    audience_hits += len(_AUDIENCE_BRIDGE_RE.findall(joined))
    audience = 0.85 if audience_hits > 0 else 0.15

    use_case_hits = len(_keyword_pattern(_USE_CASE_KEYWORDS).findall(joined))
    use_case = 0.80 if use_case_hits > 0 else 0.15

    category_hits = len(_keyword_pattern(_CATEGORY_NOUN_KEYWORDS).findall(joined))
    category_hits += len(_CATEGORY_PHRASE_RE.findall(joined))
    category = 0.90 if category_hits > 0 else 0.15

    buzz_hits = float(len(_keyword_pattern(_VAGUE_KEYWORDS).findall(joined)))
    # Hype words matter less when balanced by concrete outcomes.
    vague_density = min(
        1.0,
        buzz_hits * 0.35 / (1.0 + concrete_hits * 0.5),
    )

    mix = 0.45 * category + 0.35 * audience + 0.20 * use_case
    base_clarity = _clamp(
        mix + 0.25 * outcome - 0.30 * vague_density,
        low=0.05,
    )

    return {
        "evidence": 1.0,
        "base_clarity": round(base_clarity, 4),
        "outcome": round(outcome, 4),
        "audience": round(audience, 4),
        "use_case": round(use_case, 4),
        "category": round(category, 4),
        "vague_density": round(vague_density, 4),
        "buzz_hits": buzz_hits,
        "concrete_hits": concrete_hits,
    }


def _comprehension_risk(
    base_clarity: float,
    traits: dict[str, Any],
) -> float:
    """Per-cluster comprehension risk from unclear messaging."""
    literacy = _trait(traits, "digital_literacy")
    motivation = _trait(traits, "motivation")
    trust = _trait(traits, "trust")
    sensitivity = _clamp(
        0.40 + (1.0 - literacy) * 0.80 - motivation * 0.15,
        low=0.30,
        high=1.05,
    )
    skepticism = _clamp(0.90 + (1.0 - trust) * 0.20, low=0.90, high=1.10)
    return round(
        _clamp((1.0 - base_clarity) * sensitivity * skepticism, high=0.95),
        4,
    )


class MessagingClarityArchitect(BaseArchitect):
    """Evaluates value-proposition comprehension risk across all clusters."""

    @property
    def name(self) -> str:
        return "MessagingClarityArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Every startup must be understood before it is bought.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        aov = _safe_float(env_params.get("average_order_value"), 0.0)
        high_ticket = aov >= _HIGH_TICKET_AOV

        texts = _collect_texts(assumptions, env_params)
        signals = _signal_scores(texts)
        evidence = bool(texts)

        if not evidence:
            clarity = 1.0
            risk = 0.0
            base_clarity = 1.0
            suppressor = 1.0
            active = False
        else:
            base_clarity = float(signals["base_clarity"])
            risk = _comprehension_risk(base_clarity, traits)
            clarity = round(max(0.05, 1.0 - risk), 4)
            if base_clarity >= _CLEAR_THRESHOLD:
                suppressor = 1.0
                active = False
            else:
                suppressor = round(
                    _clamp(
                        0.55 + clarity * 0.45,
                        low=_SUPPRESSOR_FLOOR,
                    ),
                    4,
                )
                active = suppressor < 1.0

        critical = active and clarity < _CRITICAL_CLARITY_THRESHOLD
        severity = (
            "CRITICAL"
            if critical
            else "WARNING"
            if active
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "messaging_clarity_score": clarity,
                "comprehension_risk": risk,
                "vague_language_density": float(signals["vague_density"]),
                "outcome_specificity": float(signals["outcome"]),
                "audience_specificity": float(signals["audience"]),
                "category_anchor_score": float(signals["category"]),
                "use_case_specificity": float(signals["use_case"]),
                "clarity_funnel_suppressor": suppressor,
            },
            flags={
                "clarity_gap": active,
                "vague_messaging": evidence and signals["vague_density"] >= 0.30,
                "missing_outcome_specificity": (
                    evidence and signals["outcome"] < 0.5
                ),
                "missing_audience": evidence and signals["audience"] < 0.5,
                "missing_category_anchor": (
                    evidence and signals["category"] < 0.5
                ),
                "missing_use_case": evidence and signals["use_case"] < 0.5,
                "high_ticket_comprehension_risk": active and high_ticket,
                "messaging_evidence_absent": not evidence,
            },
            narrative_findings=[
                (
                    f"Messaging clarity: {clarity:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                ),
                (
                    f"Signals: {signals['buzz_hits']:.0f} hype word(s), "
                    f"{signals['concrete_hits']:.0f} outcome(s), "
                    f"audience={'yes' if signals['audience'] >= 0.5 else 'no'}, "
                    f"category={'yes' if signals['category'] >= 0.5 else 'no'}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("clarity_funnel_suppressor", 1.0))
        if suppressor >= 1.0:
            return {}
        overrides: dict[tuple[str, str], float] = {
            ("BROWSE", "CONSIDER"): max(0.05, min(0.999, suppressor)),
        }
        if output.flags.get("high_ticket_comprehension_risk"):
            overrides[("CONSIDER", "DECIDE")] = max(
                _DECISION_SUPPRESSOR_FLOOR,
                min(0.999, suppressor - 0.10),
            )
        return overrides

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("clarity_gap") and o.severity == "CRITICAL"]
        gaps = [o for o in outputs if o.flags.get("clarity_gap")]
        affected = list(
            dict.fromkeys(
                o.cluster_id for o in critical + gaps if o.cluster_id
            )
        )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters cannot comprehend the value "
                f"proposition; {len(gaps)} clusters show messaging-driven "
                f"funnel drop-off"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.03, 3),
            conversion_impact=round(
                len(critical) * 0.04 + (len(gaps) - len(critical)) * 0.015,
                3,
            ),
            recommended_action=(
                "Rewrite the pitch in plain language: name the category, "
                "who it is for, and one quantified outcome; test copy with "
                "low-literacy segments and replace hype words"
            ),
            severity="CRITICAL" if critical else "WARNING" if gaps else "INFO",
        )


__all__ = ["MessagingClarityArchitect"]
