"""
FounderExecutionArchitect — team / delivery-capability founder insight.

Why it exists
-------------
TheCee models demand, price, trust, retention, supply chain and cash runway
across the 52 clusters, but nothing in the live funnel accounts for the
simplest execution failure mode: the team cannot build, ship or support the
product it is selling. A pitch with perfect positioning still converts
poorly when the only evidence is an idea: risk-averse and low-trust clusters
discount offers from solo founders, unbuilt products and teams without a
support plan.

What this architect does
------------------------
* **Signal extraction** — reads the project description plus scored
  assumption texts and scores three concrete evidence groups:
  - *team evidence*: named technical leadership, co-founders, experienced
    or serial founders, engineering teams, accelerator backing;
  - *product evidence*: working prototype, live MVP, beta users, pilot
    customers, launched product, paying users;
  - *support evidence*: support team, helpdesk, warranty, refund policy,
    onboarding team, SLA.
  Detection is negation- and intent-aware: "no prototype", "still in
  development" and "plan to build the MVP" are gaps, never proof, while
  "No, we already shipped" stays evidence.
* **Delivery-risk modelling** — combines the evidence score with per-cluster
  traits: risk aversion, low trust, low income and low patience amplify the
  perceived chance that the product never arrives or never improves.
  High-ticket and long-lifetime product categories add extra stakes.
* **Funnel suppression** — when execution evidence is weak, consumers at
  the DECIDE stage hesitate to hand over money, so the DECIDE→PURCHASE
  transition is suppressed. When the brief never mentions team, prototype
  or support at all, nothing is penalised and the funnel stays neutral
  (mirroring RunwayArchitect's "not discussed" rule).
* **Founder insight** — the cross-cluster report names which segments stop
  short because the venture itself looks undeliverable and tells the founder
  exactly which evidence class (team, prototype, support) is missing.

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

_NEUTRAL_CREDIBILITY: float = 0.62      # brief never mentions execution
_STRONG_CREDIBILITY_CAP: float = 0.95
_WEAK_CREDIBILITY_FLOOR: float = 0.20
_ACTIVE_SCORE_THRESHOLD: float = 0.55   # below this, gap is active
_CRITICAL_SCORE_THRESHOLD: float = 0.38
_CRITICAL_RISK_THRESHOLD: float = 0.60
_SUPPRESSOR_FLOOR: float = 0.45
_HIGH_TICKET_AOV: float = 10_000.0

_LONGEVITY_PRODUCT_TYPES: frozenset[str] = frozenset({
    "consumer_hardware", "health_hardware", "iot_hardware", "wearable",
    "b2b_hardware", "enterprise_software", "b2b_marketplace",
})


# ── Team evidence ───────────────────────────────────────────────────────

_TEAM_STRONG_KEYWORDS: tuple[str, ...] = (
    "team of", "founding team", "core team", "co-founder", "cofounder",
    "co-founders", "cofounders", "co-founded by", "founded by",
    "technical co-founder", "technical cofounder", "technical co-founders",
    "cto", "chief technology officer", "engineering team", "engineering lead",
    "senior engineer", "senior engineers", "software engineer",
    "software engineers", "backend engineer", "frontend engineer",
    "full-stack", "full stack engineer", "engineering manager",
    "product manager", "product designers", "design team",
    "domain expert", "domain experts", "ex-google", "ex-google engineer",
    "ex-amazon", "ex-microsoft", "ex-uber", "ex-meta", "ex-flipkart",
    "ex-paytm", "ex-razorpay", "ex-zomato", "ex-swiggy",
    "serial founder", "serial entrepreneurs", "second-time founder",
    "second time founder", "experienced founder", "experienced founders",
    "experienced team", "years of experience", "years experience",
    "decade of experience", "iit", "iim", "stanford", "harvard", "mit",
    "y combinator", "yc backed", "accelerator", "incubator", "alumni",
)

_TEAM_GAP_KEYWORDS: tuple[str, ...] = (
    "solo founder", "solo-founder", "one-person team", "one person team",
    "team of one", "just me", "only me", "no team", "no co-founder",
    "no cofounder", "without a co-founder", "without a cofounder",
    "without a technical", "no technical co-founder", "no technical cofounder",
    "no technical founder", "looking for a technical co-founder",
    "looking for a technical cofounder", "need a technical co-founder",
    "needs a technical co-founder", "need a technical cofounder",
    "hiring developers", "hiring engineers", "recruiting engineers",
    "hire engineers", "hire developers", "recruit engineers",
    "cannot build", "do not have engineers",
    "do not have a team", "does not have a team", "first-time founder",
    "first time founder", "no engineering", "no engineers",
    "part-time founder", "part time founder",
)


# ── Product / delivery evidence ─────────────────────────────────────────

_PRODUCT_STRONG_KEYWORDS: tuple[str, ...] = (
    "working prototype", "prototype built", "prototype ready",
    "functional prototype", "mvp built", "mvp is built", "mvp live",
    "mvp launched", "mvp in production", "beta live", "beta launched",
    "beta is live", "beta users", "beta testers", "early users",
    "waitlist", "pilots", "pilot customers", "pilot users", "signed pilots",
    "shipped", "we shipped", "already shipped", "product is live",
    "available on the app store", "app store", "play store", "units sold",
    "first customers", "paying users", "paying customers", "in production",
    "we launched", "has launched", "have launched", "launched the product",
    "live in the", "roadmap published",
)

_PRODUCT_GAP_KEYWORDS: tuple[str, ...] = (
    "no prototype", "no mvp", "no beta", "no product yet", "not built",
    "have not built", "has not built", "not built yet", "still in development",
    "still building", "currently building", "building the mvp",
    "building mvp", "building a prototype", "developing the app",
    "developing the product", "plan to build", "plans to build",
    "will build", "going to build", "want to build", "need to build",
    "needs to build", "must build", "should build", "pre-launch",
    "pre launch", "pre-product", "pre product", "idea stage",
    "concept stage", "paper prototype", "wireframe", "mockup",
    "just an idea", "only an idea", "not launched", "has not launched",
    "have not launched", "planning to launch", "plans to launch",
    "will launch", "launching soon", "coming soon", "not available yet",
    "not on the market", "no users yet", "no customers yet",
    "no paying customers",
)


# ── Support / fulfilment evidence ───────────────────────────────────────

_SUPPORT_STRONG_KEYWORDS: tuple[str, ...] = (
    "support team", "customer support", "customer success", "helpdesk",
    "support plan", "onboarding team", "warranty", "refund policy",
    "returns policy", "sla", "service level agreement", "24/7 support",
    "24x7 support", "support engineers", "success manager",
)

_SUPPORT_GAP_KEYWORDS: tuple[str, ...] = (
    "no support", "no customer support", "no helpdesk", "no warranty",
    "no refunds", "no refund policy", "cannot support",
    "will not provide support", "without support", "no support team",
)


# Phrases whose leading negation is part of the meaning ("no prototype",
# "not built", "haven't built") and must not be voided by the generic
# negation scanner.
_GAP_NEGATION_IS_THE_SIGNAL: frozenset[str] = frozenset({
    "no prototype", "no mvp", "no beta", "no product yet", "not built",
    "have not built", "has not built", "not built yet", "no team",
    "no co-founder", "no cofounder", "without a co-founder",
    "without a cofounder", "without a technical", "no technical co-founder",
    "no technical cofounder", "no technical founder", "no engineering",
    "no engineers", "not launched", "has not launched", "have not launched",
    "no users yet", "no customers yet", "no paying customers",
    "no support", "no customer support", "no helpdesk", "no warranty",
    "no refunds", "no refund policy", "no support team", "without support",
    "cannot build", "do not have engineers", "do not have a team",
    "does not have a team", "cannot support", "will not provide support",
})

# Intent markers: a plan, roadmap or requirement is not proof that the
# product exists. "plan to build", "will launch" and "need a technical
# co-founder" describe intent, not shipped reality.
_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "would", "intend", "intends", "intended",
    "aim", "aims", "hoping", "hope", "hopes", "want", "wants", "wanted",
    "scheduled", "upcoming", "due", "target", "targets", "targeting",
    "looking", "explore", "exploring", "evaluate", "evaluating",
    "expect", "expects", "expected", "expecting", "anticipate",
    "anticipates", "anticipated", "anticipating", "aiming", "intending",
    "hopefully", "hoped", "almost", "nearly", "maybe", "perhaps",
    "possibly", "probably", "likely", "projected", "projection",
    "tentative", "tentatively", "about to",
})

_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "unconfirmed", "pending", "awaiting", "awaited",
    "outstanding", "incomplete", "suspended", "rejected", "denied",
    "withdrawn", "expired", "revoked", "void", "failed", "unavailable",
    "unsecured", "unsigned", "unbuilt", "unlaunched",
})

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
    r"[.,;:!?—–\n]|\b(?:but|yet|though|although|whereas|however|while)\b",
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
    """Gather pitch texts: scored assumptions plus project description.

    Null or blank entries are not evidence: a database row with ``text=None``
    must not be read as the literal string "None". Identical texts are
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
    # Preserve order while removing duplicate pitch texts.
    return list(dict.fromkeys(texts))


def _is_discourse_negation(tokens: list[str]) -> bool:
    """True for "not only"/"not just" focus constructions."""
    focus = {"only", "just", "merely", "simply"}
    return any(
        tokens[i] == "not"
        and i + 1 < len(tokens)
        and tokens[i + 1] in focus
        for i in range(len(tokens) - 1)
    )


def _match_context(
    text: str,
    start: int,
    end: int,
) -> tuple[list[str], list[str], str]:
    """Return (before, after, before_text) for the clause around a match."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    if after and after[0] in {"and", "or", "then", "also", "plus", "too"}:
        after = []
    before_text = " ".join(before)
    return before, after, before_text


def _match_is_voided(
    text: str,
    start: int,
    end: int,
) -> bool:
    """True when negation/intent markers qualify a strong-evidence match."""
    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    # A keyword inside an interrogative clause ("Do we have a prototype?")
    # is a question, not evidence.
    if clause_end < len(text) and text[clause_end] == "?":
        return True

    before, after, before_text = _match_context(text, start, end)
    combined = before + after

    if any(
        phrase in before_text
        for phrase in ("working on", "in progress", "to be")
    ):
        return True
    if _is_discourse_negation(combined):
        negation_voided = False
    else:
        negation_voided = bool(set(combined) & _NEGATION_MARKERS)
    # Intent markers only void strong evidence when they precede the
    # keyword ("we plan to launch", "we will build the MVP"). Markers in
    # the trailing clause ("we launched to build momentum") explain the
    # fact rather than making it aspirational.
    return negation_voided or bool(set(before) & _INTENT_MARKERS)


def _is_negated(
    text: str,
    start: int,
    end: int,
) -> bool:
    """True when negation markers (not intent alone) qualify a match."""
    before, after, _ = _match_context(text, start, end)
    combined = before + after
    if _is_discourse_negation(combined):
        return False
    return bool(set(combined) & _NEGATION_MARKERS)


def _count_strong(
    joined: str,
    keywords: tuple[str, ...],
) -> int:
    pattern = _keyword_pattern(keywords)
    count = 0
    for match in pattern.finditer(joined):
        if not _match_is_voided(joined, match.start(), match.end()):
            count += 1
    return count


def _count_gaps(
    joined: str,
    keywords: tuple[str, ...],
) -> int:
    """Count gap matches; negation/intent inside the phrase is the signal."""
    pattern = _keyword_pattern(keywords)
    count = 0
    for match in pattern.finditer(joined):
        matched = joined[match.start():match.end()].lower()
        if matched in _GAP_NEGATION_IS_THE_SIGNAL:
            count += 1
            continue
        tokens = set(re.findall(r"[a-z]+", matched))
        if tokens & _INTENT_MARKERS:
            count += 1
            continue
        if not _match_is_voided(joined, match.start(), match.end()):
            count += 1
    return count


def _count_negated_evidence(
    joined: str,
    keywords: tuple[str, ...],
) -> int:
    """Count strong-evidence phrases negated in the text ("no prototype")."""
    pattern = _keyword_pattern(keywords)
    count = 0
    for match in pattern.finditer(joined):
        if _match_is_voided(joined, match.start(), match.end()) and _is_negated(
            joined, match.start(), match.end()
        ):
            count += 1
    return count


def _signal_scores(texts: list[str]) -> dict[str, float]:
    """Derive text-level execution evidence, all deterministic and bounded."""
    if not texts:
        return {
            "evidence": 0.0,
            "team": 0.0,
            "team_gap": 0.0,
            "product": 0.0,
            "product_gap": 0.0,
            "support": 0.0,
            "support_gap": 0.0,
        }

    joined = "\n".join(texts)
    team_gap = float(
        _count_gaps(joined, _TEAM_GAP_KEYWORDS)
        + _count_negated_evidence(joined, _TEAM_STRONG_KEYWORDS)
    )
    product_gap = float(
        _count_gaps(joined, _PRODUCT_GAP_KEYWORDS)
        + _count_negated_evidence(joined, _PRODUCT_STRONG_KEYWORDS)
    )
    support_gap = float(
        _count_gaps(joined, _SUPPORT_GAP_KEYWORDS)
        + _count_negated_evidence(joined, _SUPPORT_STRONG_KEYWORDS)
    )
    return {
        "evidence": 1.0,
        "team": float(_count_strong(joined, _TEAM_STRONG_KEYWORDS)),
        "team_gap": team_gap,
        "product": float(_count_strong(joined, _PRODUCT_STRONG_KEYWORDS)),
        "product_gap": product_gap,
        "support": float(_count_strong(joined, _SUPPORT_STRONG_KEYWORDS)),
        "support_gap": support_gap,
    }


def _credibility_score(signals: dict[str, float]) -> float:
    """Combine evidence and gap counts into one 0-1 credibility score."""
    team = float(signals["team"])
    team_gap = float(signals["team_gap"])
    product = float(signals["product"])
    product_gap = float(signals["product_gap"])
    support = float(signals["support"])
    support_gap = float(signals["support_gap"])

    strength = _clamp(
        0.14 * min(team, 2.0)
        + 0.20 * min(product, 2.0)
        + 0.08 * min(support, 2.0),
        high=0.42,
    )
    penalty = _clamp(
        0.20 * team_gap
        + 0.26 * product_gap
        + 0.14 * support_gap,
        high=0.56,
    )
    return round(
        _clamp(
            _NEUTRAL_CREDIBILITY + strength - penalty,
            low=_WEAK_CREDIBILITY_FLOOR,
            high=_STRONG_CREDIBILITY_CAP,
        ),
        4,
    )


def _delivery_sensitivity(
    traits: dict[str, Any],
    product_type: str,
    high_ticket: bool,
) -> float:
    """Per-cluster sensitivity to delivery/execution risk."""
    risk_av = _trait(traits, "risk_aversion")
    trust = _trait(traits, "trust")
    income = _trait(traits, "income_level")
    patience = _trait(traits, "patience_score")
    stakes = 0.12 if product_type in _LONGEVITY_PRODUCT_TYPES else 0.0
    if high_ticket:
        stakes += 0.08
    return _clamp(
        0.32
        + risk_av * 0.30
        + (1.0 - trust) * 0.22
        + (1.0 - income) * 0.12
        + (1.0 - patience) * 0.10
        + stakes,
        low=0.22,
        high=1.0,
    )


class FounderExecutionArchitect(BaseArchitect):
    """Evaluates team / delivery-capability risk across all clusters."""

    @property
    def name(self) -> str:
        return "FounderExecutionArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Every startup must be able to build and ship what it
        # sells, so the domain is universal.
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
        aov = _safe_float(env_params.get("average_order_value"), 0.0)
        high_ticket = aov >= _HIGH_TICKET_AOV

        texts = _collect_texts(assumptions, env_params)
        signals = _signal_scores(texts)
        evidence = bool(texts)

        if not evidence:
            score = _NEUTRAL_CREDIBILITY
            risk = 0.0
            suppressor = 1.0
            active = False
        else:
            score = _credibility_score(signals)
            sensitivity = _delivery_sensitivity(
                traits,
                product_type,
                high_ticket,
            )
            risk = round(_clamp((1.0 - score) * sensitivity, high=0.95), 4)
            active = (
                float(signals["team_gap"]) > 0.0
                or float(signals["product_gap"]) > 0.0
                or float(signals["support_gap"]) > 0.0
                or score < _ACTIVE_SCORE_THRESHOLD
            )
            if active:
                suppressor = round(
                    _clamp(
                        1.0 - risk * 0.68,
                        low=_SUPPRESSOR_FLOOR,
                    ),
                    4,
                )
            else:
                suppressor = 1.0

        critical = active and (
            risk >= _CRITICAL_RISK_THRESHOLD
            or (
                score < _CRITICAL_SCORE_THRESHOLD
                and risk >= 0.45
            )
        )
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
                "execution_credibility_score": round(score, 4),
                "delivery_risk": risk,
                "execution_funnel_suppressor": suppressor,
                "team_evidence_strength": round(
                    min(1.0, float(signals["team"]) / 3.0), 4
                ),
                "prototype_evidence_strength": round(
                    min(1.0, float(signals["product"]) / 3.0), 4
                ),
                "support_evidence_strength": round(
                    min(1.0, float(signals["support"]) / 2.0), 4
                ),
            },
            flags={
                "execution_gap": active,
                "delivery_risk_active": active,
                "team_evidence_present": bool(signals["team"]),
                "prototype_evidence_present": bool(signals["product"]),
                "support_evidence_present": bool(signals["support"]),
                "solo_founder_gap": bool(signals["team_gap"]),
                "unbuilt_product_gap": bool(signals["product_gap"]),
                "support_gap": bool(signals["support_gap"]),
                "execution_evidence_absent": not evidence,
            },
            narrative_findings=[
                (
                    f"Execution credibility: {score:.2f} | "
                    f"Delivery risk: {risk:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                ),
                (
                    f"Evidence: team={signals['team']:.0f}+"
                    f"{signals['team_gap']:.0f}-, "
                    f"product={signals['product']:.0f}+"
                    f"{signals['product_gap']:.0f}-, "
                    f"support={signals['support']:.0f}+"
                    f"{signals['support_gap']:.0f}-"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("execution_funnel_suppressor", 1.0))
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
            o
            for o in outputs
            if o.flags.get("execution_gap") and o.severity == "CRITICAL"
        ]
        gaps = [o for o in outputs if o.flags.get("execution_gap")]
        affected = list(
            dict.fromkeys(
                o.cluster_id for o in critical + gaps if o.cluster_id
            )
        )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters discount the offer on "
                f"execution/delivery risk; {len(gaps)} clusters show "
                f"execution-driven purchase drop-off"
            ),
            affected_cluster_ids=affected,
            # Flat per-cluster share approximation (0.03) must never
            # exceed the whole population.
            population_fraction=round(min(1.0, len(affected) * 0.03), 3),
            conversion_impact=round(
                len(critical) * 0.04 + (len(gaps) - len(critical)) * 0.015,
                3,
            ),
            recommended_action=(
                "Publish execution proof: working prototype or live MVP, "
                "named technical team, beta users, and a support/refund plan"
            ),
            severity="CRITICAL" if critical else "WARNING" if gaps else "INFO",
        )


__all__ = ["FounderExecutionArchitect"]
