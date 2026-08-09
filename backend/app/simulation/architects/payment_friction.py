"""
PaymentFrictionArchitect — payment-method coverage, checkout friction,
cash dependency and financing gaps across the 52 consumer clusters.

Startups leak conversions at the last metre when the buyer cannot pay the
way they want: a Tier-3 cash-first household bounces from a credit-card-only
checkout, a price-sensitive hardware buyer needs EMI/BNPL, an overseas user
needs multi-currency or international cards, and a B2B buyer needs invoices
or net terms. The rest of the engine models price (can the buyer afford it?),
trust (do they believe it?) and distribution (can they reach it?), but has no
dedicated signal for whether the founder's assumptions actually cover how the
buyer will pay.

What this architect does:

* **Signal detection** — scans assumption text for payment-method coverage,
  checkout friction, financing (EMI/BNPL/installments/invoices) and
  international-payment exposure. A small baseline keeps funnels neutral
  until the founder mentions payments.
* **Gap modelling** — method coverage drops when checkout is restricted
  ("credit card only", "requires invoice") or no payment evidence exists;
  cash dependency scales with low income/literacy, risk aversion, price
  sensitivity and non-metro geography; financing dependency scales with
  price sensitivity, low income and high average order value.
* **Credibility** — payment evidence (UPI enabled, COD available, cards
  accepted, EMI offered, international payments accepted, invoice billing,
  ...) raises ``payment_credibility`` to 1.0, softens the funnel suppressor
  and earns a small purchase-stage ``payment_advantage_lift``. Detection is
  negation- and discourse-aware: "no UPI", "COD unavailable", "doesn't
  accept cards" and "payments aren't integrated" are gaps, never evidence,
  while "No, we already accept UPI and COD" stays evidence.
* **Markov overrides** — only when payment exposure is active:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + payment_advantage_lift`` when evidence exists.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_PAYMENT_KEYWORDS: tuple[str, ...] = (
    "upi", "cash on delivery", "cod", "debit card", "debit cards",
    "credit card", "credit cards", "net banking", "netbanking",
    "wallet", "wallets", "paytm", "phonepe", "google pay", "gpay",
    "payment gateway", "payment method", "payment methods",
    "bank transfer", "bank transfers", "paypal", "stripe", "razorpay",
    "checkout", "emi", "installment", "installments",
    "buy now pay later", "bnpl", "invoice", "net terms",
    "international payment", "international payments",
    "multi-currency", "multicurrency", "currency conversion",
    "foreign transaction", "cash payment", "offline payment",
)

_CHECKOUT_KEYWORDS: tuple[str, ...] = (
    "checkout", "payment gateway", "payment method", "payment methods",
    "otp", "one-time password", "kyc", "payment failure",
    "payment failures", "declined", "card declined",
    "international transaction", "foreign transaction",
    "currency conversion", "fx fee", "card required",
    "credit card required", "debit card required",
    "only credit card", "credit card only", "only debit card",
    "debit card only",
)

_FINANCING_KEYWORDS: tuple[str, ...] = (
    "emi", "installment", "installments", "buy now pay later", "bnpl",
    "no-cost emi", "subscription billing", "annual plan",
    "annual billing", "monthly plan", "net terms", "invoice",
)

_INTERNATIONAL_KEYWORDS: tuple[str, ...] = (
    "international payment", "international payments",
    "international transaction", "multi-currency", "multicurrency",
    "multiple currencies", "currency conversion", "foreign transaction",
    "fx fee", "overseas", "cross-border",
)

_RESTRICTED_KEYWORDS: tuple[str, ...] = (
    "only credit card", "credit card only", "requires credit card",
    "require credit card", "requires a credit card",
    "require a credit card", "credit card required",
    "only debit card", "debit card only", "requires a debit card",
    "require a debit card", "debit card required",
    "international cards only", "only international cards",
    "us bank account only", "invoice only", "net terms only",
    "cash only", "cod only", "requires invoice", "require invoice",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "accepts upi", "accept upi", "accepts upi payments",
    "upi accepted", "upi is accepted", "upi enabled", "upi support",
    "upi supported", "upi payments", "upi integrated", "integrated upi",
    "upi available", "cash on delivery available", "cod available",
    "accepts cod", "accept cod", "cash on delivery supported",
    "cash on delivery support", "cash payment accepted",
    "cash payment accepted at delivery", "offline payment",
    "offline payments", "accepts cash", "accept cash",
    "debit cards accepted", "debit card accepted",
    "accepts debit cards", "accept debit cards", "debit card support",
    "debit card supported", "credit cards accepted",
    "credit card accepted", "accepts credit cards",
    "accept credit cards", "credit card support",
    "credit card supported", "net banking accepted",
    "netbanking accepted", "net banking support",
    "net banking available", "accepts net banking",
    "accept net banking", "wallet payments accepted",
    "accepts wallets", "accept wallets", "paytm accepted",
    "phonepe accepted", "google pay accepted", "upi and cod",
    "upi, cod", "multiple payment methods",
    "payment methods supported", "payment gateway integrated",
    "payment gateway integration", "razorpay", "stripe", "paypal",
    "bank transfer", "bank transfers", "ach", "sepa",
    "international payments accepted", "accepts international payments",
    "accept international payments", "international cards accepted",
    "multi-currency support", "multicurrency support",
    "multiple currencies supported", "currency conversion",
    "invoice billing", "invoice payment", "net terms available",
    "net terms offered", "monthly invoicing",
    "emi available", "emi offered", "emi options", "no-cost emi",
    "installment plans", "installment plan available",
    "installments available", "buy now pay later available",
    "bnpl available", "subscription billing", "annual plan",
    "monthly plan",
)

_CASH_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "cash on delivery", "cod", "cash payment", "cash payments",
    "cash on delivery available", "cod available",
    "cash on delivery supported", "cash on delivery support",
    "cash payment accepted", "cash payment accepted at delivery",
    "accepts cod", "accept cod", "accepts cash", "accept cash",
    "cash accepted", "pay at store", "upi and cod", "upi, cod",
    "accepts offline payments", "accept offline payments",
    "offline payment", "offline payments", "offline payments available",
)

_FINANCING_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "emi", "installment", "installments", "buy now pay later", "bnpl",
    "no-cost emi", "net terms", "emi available", "emi offered",
    "emi options", "emi support",
    "emi supported", "accepts emi", "accept emi",
    "no-cost emi available", "no-cost emi offered",
    "installment plans", "installment plan available",
    "installments available", "buy now pay later available",
    "bnpl available", "subscription billing",
    "annual plan available", "monthly plan available",
    "net terms available", "net terms offered",
    "invoice billing", "invoice payment", "monthly invoicing",
)

# Absence markers that qualify a matched phrase ("no UPI", "COD
# unavailable", "payments not integrated"). Clause-leading discourse
# negation ("No, we already accept UPI") is handled separately.
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks",
    "lacking", "missing", "absent", "absence", "unclear", "uncertain",
    "unknown", "unverified", "unconfirmed", "pending", "awaiting",
    "awaited", "outstanding", "void", "expired", "revoked", "rejected",
    "denied", "withdrawn", "incomplete", "suspended", "unavailable",
    "unsupported", "not available", "not supported", "not accepted",
    "not integrated",
})

# Aspirational markers: a plan, requirement or roadmap is not evidence.
# "We need to set up UPI", "will add COD", "plan to offer EMI" describe
# intent, not a working payment flow.
_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "intend", "intends", "intended", "add",
    "adding", "build", "building", "aim", "aims", "hoping", "hope",
    "hopes", "want", "wants", "wanted", "working", "scheduled",
    "upcoming", "due", "set", "setting", "setup", "integrate",
    "integrating",
})

# Clause separators for scoping negation/intent qualifiers. Punctuation
# and contrastive conjunctions always end the scope of a qualifier; "and"
# is only a hard boundary when the phrase after it is its own clause
# ("UPI is accepted and COD is unavailable") rather than a continuation of
# a list ("don't accept UPI and COD", "plan to add UPI and EMI").
_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[.,;:!?—–\n]|\b(?:but|yet|though|although|whereas|however|while)\b",
    re.IGNORECASE,
)
_AND_BOUNDARY_PATTERN = re.compile(r"\band\b", re.IGNORECASE)
_PREDICATE_PATTERN = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|will|would|can|"
    r"could|should|must|may|might|do|does|did|plan|plans|planned|"
    r"planning|need|needs|require|requires|accept|accepts|support|"
    r"supports|offer|offers|available|unavailable)\b",
    re.IGNORECASE,
)

# Contracted negations are expanded before matching so "don't accept UPI"
# and "payments aren't integrated" are gaps, never evidence. The optional
# apostrophe also covers no-apostrophe spellings ("dont", "arent").
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

# Neutral baseline so runs that never mention payments stay unchanged.
_EXPOSURE_BASELINE: float = 0.08
_SIGNAL_STEP: float = 0.18
_EXPOSURE_CAP: float = 0.95
_OVERRIDE_THRESHOLD: float = 0.15
_SUPPRESSOR_MIN: float = 0.55
_MAX_SUPPRESSION: float = 0.40
_MAX_ADVANTAGE_LIFT: float = 0.12
_CHECKOUT_BLOCKER: float = 0.40
_METHOD_GAP: float = 0.70
_CASH_GAP: float = 0.50
_FINANCING_GAP: float = 0.50


@lru_cache(maxsize=8)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _normalize(text: str) -> str:
    """Lowercase and expand contracted negations for gap detection."""
    text = text.lower().replace("’", "'")
    return _CONTRACTION_PATTERN.sub(
        lambda m: _CONTRACTION_SUFFIXES[m.group(1)], text
    )


def _discourse_marker(text: str, start: int) -> str | None:
    """
    Return a clause-leading negation marker when it is discourse rather
    than a qualifier: "No, we already accept UPI" or "Not only do we
    accept cards". Otherwise return None.
    """
    prefix = text[:start]
    boundary = max(prefix.rfind(c) for c in ".!?;")
    clause = text[boundary + 1:start]
    words = re.findall(r"[a-z]+", clause)
    if not words or words[0] not in _NEGATION_MARKERS:
        return None
    match = re.match(r"\s*[a-z']+", clause)
    if match is None:
        return None
    tail = clause[match.end():]
    if tail.lstrip()[:1] in {",", ".", ":", ";", "—", "–"}:
        return words[0]
    if (
        len(words) >= 2
        and words[0] in {"no", "not", "never"}
        and words[1] in {"only", "just", "merely", "simply"}
    ):
        return words[0]
    return None


def _is_negated(text: str, start: int, end: int) -> bool:
    """
    True when a negation/absence marker qualifies a match, ignoring a
    leading discourse negation while still catching qualifiers after it.
    Qualifiers are scoped to the same clause so "we accept UPI, but cards
    are not accepted" is still UPI evidence.
    """
    discourse = _discourse_marker(text, start)
    before = _same_clause_tokens(text, start, end, direction="before")
    for i, token in enumerate(before):
        if token == discourse and i == 0:
            continue
        if token in _NEGATION_MARKERS:
            return True
    after = _same_clause_tokens(text, start, end, direction="after")
    return any(token in _NEGATION_MARKERS for token in after)


def _same_clause_tokens(
    text: str,
    start: int,
    end: int,
    *,
    direction: str,
) -> list[str]:
    """
    Return the word tokens between the match and the nearest clause
    boundary in the requested direction.

    "and" is treated as a boundary only when what follows it is its own
    clause ("UPI is accepted and COD is unavailable"), so a qualifier in
    the earlier clause does not leak onto a bare list item ("don't accept
    UPI and COD" still voids both).
    """
    radius = 120
    if direction == "before":
        lo = max(0, start - radius)
        clause_start = lo
        for boundary in _CLAUSE_BOUNDARY_PATTERN.finditer(text, lo, start):
            clause_start = boundary.end()
        anchor = start
        for and_match in reversed(
            list(_AND_BOUNDARY_PATTERN.finditer(text, clause_start, anchor))
        ):
            segment = text[and_match.end():anchor]
            if _PREDICATE_PATTERN.search(segment):
                clause_start = and_match.end()
                break
            anchor = and_match.start()
        return re.findall(r"[a-z]+", text[clause_start:start])

    hi = min(len(text), end + radius)
    clause_end = hi
    for boundary in _CLAUSE_BOUNDARY_PATTERN.finditer(text, end, hi):
        clause_end = boundary.start()
        break
    for and_match in _AND_BOUNDARY_PATTERN.finditer(text, end, clause_end):
        clause_end = and_match.start()
        break
    return re.findall(r"[a-z]+", text[end:clause_end])


def _contains_intent_marker(tokens: list[str]) -> bool:
    """True when an intent/aspiration marker appears in the token list."""
    for i, token in enumerate(tokens):
        if token == "working":
            # "working on X" is intent; "UPI payments are working" is
            # evidence that the flow functions.
            if i + 1 < len(tokens) and tokens[i + 1] == "on":
                return True
            continue
        if token in _INTENT_MARKERS:
            return True
    return False


def _has_any_keyword(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
    *,
    guard_negation: bool = False,
    guard_intent: bool = False,
) -> bool:
    """
    True when any assumption text contains any keyword (word-boundary).

    With ``guard_negation``, a match is ignored when a negation/absence
    marker appears near it, so "no UPI" or "payments not integrated"
    never counts as evidence.
    """
    if not assumptions:
        return False
    pattern = _keyword_pattern(keywords)
    for assumption in assumptions:
        if isinstance(assumption, dict):
            text = _normalize(
                str(assumption.get("text", assumption.get("assumption", "")))
            )
        else:
            text = _normalize(str(assumption))
        if not guard_negation:
            if pattern.search(text):
                return True
            continue
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if guard_intent and _is_intent_qualified(text, start, end):
                continue
            if not _is_negated(text, start, end):
                return True
    return False


def _is_intent_qualified(text: str, start: int, end: int) -> bool:
    """
    True when an intent/aspiration marker qualifies the match in the same
    clause, so "we accept UPI and plan to add COD" is still UPI evidence
    while "we plan to add UPI and EMI" is not evidence.
    """
    before = _same_clause_tokens(text, start, end, direction="before")
    after = _same_clause_tokens(text, start, end, direction="after")
    return _contains_intent_marker(before) or _contains_intent_marker(after)


def _has_restricted_keyword(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
) -> bool:
    """
    True when any assumption contains a payment-restriction phrase.

    "Not only credit card but also UPI" is not a restriction, so a
    "not only" qualifier immediately before the phrase is ignored.
    """
    if not assumptions:
        return False
    pattern = _keyword_pattern(keywords)
    for assumption in assumptions:
        if isinstance(assumption, dict):
            text = _normalize(
                str(assumption.get("text", assumption.get("assumption", "")))
            )
        else:
            text = _normalize(str(assumption))
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 60):match.start()]
            before_tokens = re.findall(r"[a-z]+", before)
            if before_tokens and before_tokens[-1] in {"not", "never", "no"}:
                continue
            return True
    return False


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


def _geo_multiplier(geography: str) -> float:
    """Tier-3/rural markets depend most on cash-friendly payments."""
    geo = (geography or "").lower()
    if "tier3" in geo or "rural" in geo:
        return 1.0
    if "tier2" in geo:
        return 0.65
    return 0.35


class PaymentFrictionArchitect(BaseArchitect):
    """Evaluates payment-method coverage and checkout friction."""

    @property
    def name(self) -> str:
        return "PaymentFrictionArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty means active for every product type — consumers need UPI/
        # COD/cards, hardware buyers need EMI, and B2B buyers need invoices
        # and net terms.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        trust = _trait(traits, "trust")
        risk_av = _trait(traits, "risk_aversion")
        literacy = _trait(traits, "digital_literacy")
        income = _trait(traits, "income_level")
        price_sens = _trait(traits, "price_sensitivity")
        geo_mult = _geo_multiplier(
            str(cluster.demographic_profile.get("geography", "metro"))
        )
        aov = float(env_params.get("average_order_value", 999))
        if not math.isfinite(aov) or aov < 0:
            aov = 999.0

        signals = {
            "payment": _has_any_keyword(assumptions, _PAYMENT_KEYWORDS),
            "checkout": _has_any_keyword(assumptions, _CHECKOUT_KEYWORDS),
            "financing": _has_any_keyword(assumptions, _FINANCING_KEYWORDS),
            "international": _has_any_keyword(
                assumptions, _INTERNATIONAL_KEYWORDS
            ),
        }
        restricted = _has_restricted_keyword(
            assumptions, _RESTRICTED_KEYWORDS
        )
        evidence = _has_any_keyword(
            assumptions,
            _EVIDENCE_KEYWORDS,
            guard_negation=True,
            guard_intent=True,
        )
        cash_evidence = _has_any_keyword(
            assumptions,
            _CASH_EVIDENCE_KEYWORDS,
            guard_negation=True,
            guard_intent=True,
        )
        financing_evidence = _has_any_keyword(
            assumptions,
            _FINANCING_EVIDENCE_KEYWORDS,
            guard_negation=True,
            guard_intent=True,
        )

        mentioned = sum(1 for detected in signals.values() if detected)
        exposure = round(
            min(
                _EXPOSURE_CAP,
                _EXPOSURE_BASELINE
                + _SIGNAL_STEP * mentioned
                + (_SIGNAL_STEP if restricted else 0.0),
            ),
            4,
        )
        active = exposure > _OVERRIDE_THRESHOLD
        checkout_signal = bool(signals["checkout"] or restricted)

        # ── Payment-method coverage ─────────────────────────────────────
        if not active:
            method_coverage = 1.0
        elif restricted:
            method_coverage = 0.40
        else:
            method_coverage = 0.75 + 0.25 * float(evidence)
        method_coverage = round(_clamp(method_coverage), 4)

        # ── Digital-payment trust gap ───────────────────────────────────
        digital_trust_gap = _clamp(
            0.40 * (1.0 - trust)
            + 0.25 * risk_av
            + 0.20 * (1.0 - literacy)
            + 0.15 * (1.0 - income)
        )

        # ── Checkout friction ───────────────────────────────────────────
        checkout_friction = 0.0
        if active:
            checkout_friction = _clamp(
                exposure
                * (
                    0.30
                    + 0.60 * (1.0 - method_coverage)
                    + 0.20 * float(checkout_signal)
                )
                * (0.55 + 0.45 * digital_trust_gap)
            )
        checkout_friction = round(checkout_friction, 4)

        # ── Cash dependency ─────────────────────────────────────────────
        cash_blend = (
            0.35 * (1.0 - income)
            + 0.30 * (1.0 - literacy)
            + 0.20 * risk_av
            + 0.15 * price_sens
        )
        cash_dependency = _clamp(
            cash_blend * (0.40 + 0.60 * geo_mult)
        )
        if cash_evidence:
            cash_dependency *= 0.40
        cash_dependency = round(_clamp(cash_dependency), 4)

        # ── Financing dependency ────────────────────────────────────────
        if aov >= 15000:
            aov_mult = 1.0
        elif aov >= 5000:
            aov_mult = 0.75
        elif aov >= 1500:
            aov_mult = 0.45
        else:
            aov_mult = 0.15
        financing_blend = (
            0.40 * price_sens
            + 0.35 * (1.0 - income)
            + 0.25 * risk_av
        )
        financing_dependency = _clamp(
            financing_blend * aov_mult
        )
        if financing_evidence:
            financing_dependency *= 0.45
        financing_dependency = round(_clamp(financing_dependency), 4)

        # ── Credibility + funnel impact ─────────────────────────────────
        credibility = (
            1.0
            if evidence and not restricted
            else max(0.10, 1.0 - exposure * 0.85)
        )
        credibility = round(_clamp(credibility), 4)

        if not active:
            suppressor = 1.0
        else:
            raw_suppression = exposure * (
                0.30 * (1.0 - method_coverage)
                + 0.25 * digital_trust_gap
                + 0.20 * cash_dependency
                + 0.15 * financing_dependency
                + 0.10 * float(checkout_signal)
            )
            if evidence:
                raw_suppression *= 0.55
            suppressor = 1.0 - min(_MAX_SUPPRESSION, raw_suppression)
        suppressor = round(_clamp(suppressor, _SUPPRESSOR_MIN, 1.0), 4)

        lift = (
            round(min(_MAX_ADVANTAGE_LIFT, exposure * 0.08), 4)
            if evidence and active and not restricted
            else 0.0
        )

        flags: dict[str, bool] = {
            "checkout_blocker": checkout_friction >= _CHECKOUT_BLOCKER,
            "payment_method_gap": active and method_coverage < _METHOD_GAP,
            "cash_dependency_gap": (
                active
                and cash_dependency >= _CASH_GAP
                and not cash_evidence
            ),
            "financing_gap": (
                active
                and financing_dependency >= _FINANCING_GAP
                and not financing_evidence
            ),
            "payment_advantage": evidence and active and not restricted,
            "payment_unknown": exposure > 0.40 and not evidence,
        }

        severity = (
            "CRITICAL"
            if flags["checkout_blocker"] or flags["cash_dependency_gap"]
            else "WARNING"
            if (
                flags["payment_method_gap"]
                or flags["financing_gap"]
                or flags["payment_unknown"]
            )
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "payment_exposure": exposure,
                "payment_method_coverage": method_coverage,
                "checkout_friction": checkout_friction,
                "digital_payment_trust_gap": round(digital_trust_gap, 4),
                "cash_dependency": cash_dependency,
                "financing_dependency": financing_dependency,
                "payment_credibility": credibility,
                "funnel_suppressor": suppressor,
                "payment_advantage_lift": lift,
                "cash_gap_active": 1.0 if flags["cash_dependency_gap"] else 0.0,
                "financing_gap_active": (
                    1.0 if flags["financing_gap"] else 0.0
                ),
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Payment exposure: {exposure:.2f} | Coverage: "
                    f"{method_coverage:.2f} | Checkout friction: "
                    f"{checkout_friction:.2f}"
                ),
                (
                    f"Cash dependency: {cash_dependency:.2f} | Financing: "
                    f"{financing_dependency:.2f} | Credibility: "
                    f"{credibility:.2f}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        exposure = float(output.metrics.get("payment_exposure", 0.0))
        if exposure <= _OVERRIDE_THRESHOLD:
            return {}
        suppressor = float(output.metrics.get("funnel_suppressor", 1.0))
        lift = float(output.metrics.get("payment_advantage_lift", 0.0))
        overrides: dict[tuple[str, str], float] = {}
        if suppressor < 1.0:
            overrides[("BROWSE", "CONSIDER")] = _clamp(
                suppressor, 0.55, 0.999
            )
            overrides[("CONSIDER", "DECIDE")] = _clamp(
                suppressor + 0.05, 0.60, 0.999
            )
        if lift > 0.0:
            overrides[("DECIDE", "PURCHASE")] = _clamp(
                1.0 + lift, 0.55, 1.15
            )
        return overrides

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [
            o
            for o in outputs
            if o.flags.get("checkout_blocker")
            or o.flags.get("cash_dependency_gap")
        ]
        warning = [
            o
            for o in outputs
            if o.flags.get("payment_method_gap")
            or o.flags.get("financing_gap")
            or o.flags.get("payment_unknown")
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No payment friction blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting payment-method evidence as the "
                    "product scales"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters blocked by checkout/cash gaps; "
                f"{len(warning)} exposed to payment-method uncertainty"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.05 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Offer the payment methods each segment actually uses: "
                "UPI, COD/cash, cards, EMI/BNPL, invoices and "
                "international payments"
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["PaymentFrictionArchitect"]
