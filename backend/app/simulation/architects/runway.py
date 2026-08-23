"""
RunwayArchitect — cash-runway / funding-viability founder insight.

The two most common startup failure causes are "no market need" and "ran
out of cash". TheCee models demand, price, trust, retention and regulation
across the 52 clusters, but nothing in the live funnel accounts for the
company's own financial survival. A consumer who believes a startup may
die in three months behaves differently at the decision stage — especially
in high-ticket, long-lifetime or risk-averse segments — and this architect
models exactly that.

What this architect does:

* **Signal detection** — scans assumption text for funding, revenue and
  runway evidence ("raised $2M", "revenue positive", "12 months of
  runway") versus gap language ("pre-revenue", "bootstrapped", "seeking
  funding", "burning cash"). Detection is negation- and intent-aware:
  "not yet profitable", "plan to raise" and "haven't raised" are gaps,
  never evidence, while "No, we are profitable" stays evidence.
* **Viability modelling** — converts evidence into a per-run
  ``business_health_score`` and, per cluster, a ``viability_sensitivity``
  that scales with risk aversion, low trust, low income, low patience and
  product longevity (hardware, health, enterprise). Gap signals suppress
  the CONSIDER→DECIDE transition; confirmed funding or breakeven evidence
  removes the suppression (baseline stays neutral when the brief never
  mentions finances, so unrelated runs are unaffected).
* **Founder insight** — the cross-cluster report tells the founder which
  segments stop short because the venture itself looks fragile, and what
  evidence (funding, revenue, 12-18 month runway, published unit
  economics) closes the gap.

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

_BREAKEVEN_KEYWORDS: tuple[str, ...] = (
    "revenue positive", "revenue-generating", "revenue generating",
    "break even", "breakeven", "break-even", "profitable", "profitability",
    "cash flow positive", "cash-flow positive", "positive cash flow",
    "paying customers", "recurring revenue", "subscription revenue",
    "net positive",
)

_FUNDING_KEYWORDS: tuple[str, ...] = (
    "funded", "raised", "funding", "fundraise", "seed round", "pre-seed",
    "series a", "series b", "series c", "venture capital", "venture",
    "angel", "angels", "investor", "investors", "investment", "invested",
    "backed by", "grant", "grants", "grant funded", "crowdfunding",
    "crowd funded", "pre-seed funding",
)

_GAP_KEYWORDS: tuple[str, ...] = (
    "pre-revenue", "pre revenue", "no revenue", "zero revenue",
    "no paying customers", "unfunded", "not funded", "no funding",
    "without funding", "lack of funding", "bootstrapped", "bootstrap",
    "self-funded", "self funded",
    "seeking funding", "seeking investment", "seeking investors",
    "seeking capital", "looking for investors", "looking for funding",
    "looking for capital", "need funding", "needs funding",
    "need investment", "needs investment", "need capital", "needs capital",
    "capital required", "raising funds", "raising capital",
    "raising money", "fundraising", "fund-raising",
    "raising a seed round", "raising seed",
    "raise funding", "raise capital", "raise money", "raise investment",
    "raise a seed round", "raise seed", "raise a round",
    "need to raise", "needs to raise", "want to raise", "wants to raise",
    "hoping to raise", "planning to raise", "trying to raise",
    "looking to raise", "plan to raise", "plans to raise",
    "intend to raise", "intends to raise", "aim to raise", "aims to raise",
    "hope to raise", "hopes to raise", "expect to raise", "expects to raise",
    "seek funding", "seeks funding", "seek capital",
    "seeks capital", "seeking a seed round", "seeking pre-seed",
    "require funding", "requires funding", "required funding",
    "require capital", "requires capital", "required capital",
    "lack funding", "lacks funding", "lack capital", "lacks capital",
    "lack of capital", "lack of cash", "lack runway", "lack of runway",
    "cash constrained", "cash-strapped", "cash strapped", "burn rate",
    "burning cash", "burning through cash", "out of money",
    "out of cash", "running out of money", "running out of cash", "low runway",
    "short runway", "thin runway", "no runway", "zero runway",
    "not raised", "have not raised", "has not raised",
)

# Gap phrases whose leading negation is part of the meaning ("not funded",
# "no revenue") and must not be voided by the generic negation scanner.
_GAP_NEGATION_IS_THE_SIGNAL: frozenset[str] = frozenset({
    "no revenue", "zero revenue", "no paying customers", "not funded",
    "no funding", "without funding", "not raised", "have not raised",
    "has not raised", "no runway", "zero runway",
})

_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "unapproved", "unsigned", "unavailable", "unreleased",
    "unsupported", "unconfirmed", "pending", "awaiting", "awaited",
    "outstanding", "incomplete", "suspended", "rejected", "denied",
    "withdrawn", "expired", "revoked", "void", "failed",
})

_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "intend", "intends", "intended", "add",
    "adding", "build", "building", "aim", "aims", "hoping", "hope",
    "hopes", "want", "wants", "wanted", "scheduled", "upcoming", "due",
    "set", "setting", "setup", "integrate", "integrating", "getting",
    "get", "obtain", "obtaining", "pursue", "pursuing", "working on",
    "in progress", "to be", "seek", "seeks", "seeking", "look for",
    "looking for",
})

_SELF_FUNDING_MARKERS: frozenset[str] = frozenset({
    "self", "bootstrapped", "bootstrap",
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
    r"[.,;:!?—–\n]|\b(?:but|though|although|whereas|however|while)\b",
    re.IGNORECASE,
)

# ── Amount / runway parsers ─────────────────────────────────────────────

_AMOUNT_NUMBER = r"([\d][\d,]*(?:\.\d+)?)"
_AMOUNT_CURRENCY = r"(?:[$₹£€]|usd|inr|rs\.?)"
_AMOUNT_UNIT = r"(?:billion|bn|b|million|mn|m|thousand|k|lakh|crore)"

_RAISED_PATTERN = re.compile(
    rf"(?:raised|secured|closed|obtained|received|committed|"
    rf"backed by|funding of|investment of|fundraise? of|"
    rf"seed(?: round)? of|series [abc](?: round)? of|round of)\s*"
    rf"(?:{_AMOUNT_CURRENCY}\s*)?{_AMOUNT_NUMBER}\s*({_AMOUNT_UNIT})?",
    re.IGNORECASE,
)

_RUNWAY_MONTHS_PATTERN = re.compile(
    rf"\b{_AMOUNT_NUMBER}\s*(?:-|–)?\s*months?\s*(?:of\s+)?(?:cash\s+)?runway\b"
    rf"|\brunway\s*(?:is\s+|stands?\s+at\s+|of\s+)?(?:cash\s+)?"
    rf"{_AMOUNT_NUMBER}\s*months?\b",
    re.IGNORECASE,
)

# Currency-normalisation to USD millions (approximate, deterministic).
_USD_UNITS: dict[str, float] = {
    "k": 0.001, "thousand": 0.001,
    "m": 1.0, "mn": 1.0, "million": 1.0,
    "b": 1000.0, "bn": 1000.0, "billion": 1000.0,
    "lakh": 0.1, "crore": 10.0,
}
_INR_UNITS: dict[str, float] = {
    "k": 0.000012, "thousand": 0.000012,
    "m": 0.012, "mn": 0.012, "million": 0.012,
    "b": 12.0, "bn": 12.0, "billion": 12.0,
    "lakh": 0.0012, "crore": 0.12,
}
_INR_CURRENCY_TOKENS: frozenset[str] = frozenset({"₹", "inr", "rs"})
_NO_UNIT_DEFAULT_MULTIPLIER = {"inr": 0.0012, "usd": 0.001}

# ── Model constants ─────────────────────────────────────────────────────

_STRONG_HEALTH: float = 0.88           # >= $2M equivalent raised
_MODERATE_HEALTH: float = 0.78         # >= $0.5M equivalent raised
_WEAK_HEALTH: float = 0.65             # small raise
_CLAIM_HEALTH: float = 0.72            # vague funding claim ("we're funded")
_BREAKEVEN_HEALTH: float = 0.95
_GAP_HEALTH: float = 0.30
_GAP_CAP: float = 0.60
_STRONG_GAP_CAP: float = 0.45

_SUPPRESSOR_FLOOR: float = 0.40
_ACTIVE_SUPPRESSOR_THRESHOLD: float = 0.999
_ACTIVE_HEALTH_THRESHOLD: float = 0.70

_LONGEVITY_PRODUCT_TYPES: frozenset[str] = frozenset({
    "consumer_hardware", "health_hardware", "iot_hardware", "wearable",
    "b2b_hardware", "enterprise_software", "b2b_marketplace",
})

_HIGH_TICKET_AOV: float = 10000.0


@lru_cache(maxsize=16)
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


def _assumption_texts(
    assumptions: list[dict[str, Any]] | None,
) -> list[str]:
    texts: list[str] = []
    for assumption in assumptions or []:
        if isinstance(assumption, dict):
            raw = str(assumption.get("text", assumption.get("assumption", "")))
        else:
            raw = str(assumption)
        texts.append(_normalise(raw))
    return texts


def _is_discourse_negation(tokens: list[str]) -> bool:
    """True for "not only"/"not just" focus constructions."""
    focus = {"only", "just", "merely", "simply"}
    return any(
        tokens[i] == "not"
        and i + 1 < len(tokens)
        and tokens[i + 1] in focus
        for i in range(len(tokens) - 1)
    )


def _match_is_voided(
    text: str,
    start: int,
    end: int,
    *,
    include_intent: bool = True,
    include_self_funding: bool = False,
) -> bool:
    """True when negation/intent/self-funding markers qualify a match."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    # A keyword inside an interrogative clause ("Are you profitable?",
    # "How much did we raise?") is a question, not evidence.
    if clause_end < len(text) and text[clause_end] == "?":
        return True

    if after and after[0] in {"and", "or", "then", "also", "plus", "too"}:
        after = []
    before_text = " ".join(before)
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
    if include_self_funding and bool(set(before[-2:]) & _SELF_FUNDING_MARKERS):
        return True
    # Intent markers only void evidence when they precede the keyword
    # ("we will have 18 months", "we plan to raise $2M"). Markers in the
    # trailing clause ("we raised $2M to build the product", "we are
    # profitable because we plan to expand") explain the fact rather than
    # making it aspirational.
    return negation_voided or (include_intent and bool(set(before) & _INTENT_MARKERS))


def _has_evidence(
    texts: list[str],
    keywords: tuple[str, ...],
    *,
    include_self_funding: bool = False,
) -> bool:
    pattern = _keyword_pattern(keywords)
    for text in texts:
        for match in pattern.finditer(text):
            if not _match_is_voided(
                text,
                match.start(),
                match.end(),
                include_self_funding=include_self_funding,
            ):
                return True
    return False


def _count_gaps(texts: list[str]) -> int:
    """Count gap matches, keeping negation-as-signal phrases intact."""
    pattern = _keyword_pattern(_GAP_KEYWORDS)
    count = 0
    for text in texts:
        for match in pattern.finditer(text):
            matched = text[match.start():match.end()].lower()
            if matched in _GAP_NEGATION_IS_THE_SIGNAL:
                count += 1
            elif not _match_is_voided(text, match.start(), match.end(), include_intent=False):
                count += 1
    return count


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _parse_raised_amounts(texts: list[str]) -> list[float]:
    """Parse raised amounts into USD millions (approximate, deterministic)."""
    amounts: list[float] = []
    for text in texts:
        for match in _RAISED_PATTERN.finditer(text):
            if _match_is_voided(text, match.start(), match.end()):
                continue
            raw = match.group(1)
            unit = (match.group(2) or "").lower()
            number = _parse_number(raw)
            if number <= 0:
                continue
            currency_match = re.search(_AMOUNT_CURRENCY, text[match.start():match.end()])
            currency = ""
            if currency_match:
                currency = currency_match.group(0).lower()

            if unit:
                table = _INR_UNITS if currency in _INR_CURRENCY_TOKENS else _USD_UNITS
                multiplier = table.get(unit)
            elif currency in _INR_CURRENCY_TOKENS:
                multiplier = _NO_UNIT_DEFAULT_MULTIPLIER["inr"]
            elif currency:
                multiplier = _NO_UNIT_DEFAULT_MULTIPLIER["usd"]
            else:
                continue
            if multiplier is None:
                continue
            amounts.append(round(number * multiplier, 4))
    return amounts


def _parse_runway_months(texts: list[str]) -> int | None:
    """Return the largest explicit runway month count, or None."""
    best: int | None = None
    for text in texts:
        for match in _RUNWAY_MONTHS_PATTERN.finditer(text):
            if _match_is_voided(text, match.start(), match.end()):
                continue
            raw = match.group(1) or match.group(2)
            if raw is None:
                continue
            months = int(float(raw.replace(",", "")))
            if months <= 0:
                continue
            if best is None or months > best:
                best = months
    return best


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


def _business_health(
    *,
    breakeven: bool,
    funding_claim: bool,
    total_raised: float,
    runway_months: int | None,
    gap_count: int,
) -> float | None:
    """Derive a single 0-1 viability score from all financial signals."""
    if breakeven:
        health = _BREAKEVEN_HEALTH
    elif total_raised >= 2.0:
        health = _STRONG_HEALTH
    elif total_raised >= 0.5:
        health = _MODERATE_HEALTH
    elif total_raised > 0.0:
        health = _WEAK_HEALTH
    elif funding_claim:
        health = _CLAIM_HEALTH
    elif runway_months is not None and runway_months >= 18:
        health = 0.85
    elif runway_months is not None and runway_months >= 12:
        health = 0.75
    elif runway_months is not None and runway_months >= 6:
        health = 0.58
    elif runway_months is not None:
        health = 0.42
    elif gap_count > 0:
        health = _GAP_HEALTH
    else:
        return None

    if gap_count > 0 and not breakeven:
        health = min(health, _GAP_CAP)
    if gap_count >= 3:
        health = min(health, _STRONG_GAP_CAP)
    return round(health, 4)


def _viability_sensitivity(
    traits: dict[str, Any],
    product_type: str,
    high_ticket: bool,
) -> float:
    risk_av = _trait(traits, "risk_aversion")
    trust = _trait(traits, "trust")
    income = _trait(traits, "income_level")
    patience = _trait(traits, "patience_score")
    stakes = 0.20 if product_type in _LONGEVITY_PRODUCT_TYPES else 0.0
    if high_ticket:
        stakes += 0.10
    return _clamp(
        0.25
        + risk_av * 0.35
        + (1.0 - trust) * 0.20
        + (1.0 - income) * 0.10
        + (1.0 - patience) * 0.10
        + stakes,
        low=0.15,
        high=0.95,
    )


def _exposure_for(
    *,
    breakeven: bool,
    funding_claim: bool,
    total_raised: float,
    runway_months: int | None,
    gap_count: int,
    active: bool,
) -> float:
    if not active:
        return 0.0
    if breakeven:
        exposure = 0.60
    elif total_raised >= 2.0:
        exposure = 0.70
    elif total_raised > 0.0 or funding_claim:
        exposure = 0.50
    elif runway_months is not None:
        exposure = 0.55
    else:
        exposure = 0.40
    if gap_count > 0 and not breakeven:
        exposure = min(exposure, 0.55)
    return round(exposure, 4)


class RunwayArchitect(BaseArchitect):
    """Evaluates cash-runway / funding-viability risk across all clusters."""

    @property
    def name(self) -> str:
        return "RunwayArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Every startup can run out of cash before finding
        # product-market fit, so the domain is universal.
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
        price_ceiling = _safe_float(agent_profile.get("price_ceiling"), 0.0)
        high_ticket = aov >= _HIGH_TICKET_AOV or price_ceiling >= _HIGH_TICKET_AOV

        texts = _assumption_texts(assumptions)
        breakeven = _has_evidence(texts, _BREAKEVEN_KEYWORDS)
        funding_claim = _has_evidence(
            texts,
            _FUNDING_KEYWORDS,
            include_self_funding=True,
        )
        raised_amounts = _parse_raised_amounts(texts)
        total_raised = max(raised_amounts, default=0.0)
        runway_months = _parse_runway_months(texts)
        gap_count = _count_gaps(texts)

        health = _business_health(
            breakeven=breakeven,
            funding_claim=funding_claim,
            total_raised=total_raised,
            runway_months=runway_months,
            gap_count=gap_count,
        )
        sensitivity = _viability_sensitivity(traits, product_type, high_ticket)

        if health is None or health >= _ACTIVE_HEALTH_THRESHOLD:
            suppressor = 1.0
        else:
            suppressor = max(
                _SUPPRESSOR_FLOOR,
                1.0 - (1.0 - health) * sensitivity * 0.90,
            )
        active = health is not None and suppressor < _ACTIVE_SUPPRESSOR_THRESHOLD
        exposure = _exposure_for(
            breakeven=breakeven,
            funding_claim=funding_claim,
            total_raised=total_raised,
            runway_months=runway_months,
            gap_count=gap_count,
            active=active,
        )

        explicit_short_runway = (
            runway_months is not None and runway_months < 6
        )
        viability_critical = active and (
            (health is not None and health <= 0.45 and suppressor <= 0.70)
            or (explicit_short_runway and health is not None and health <= 0.50)
        )
        runway_gap = active or (
            runway_months is not None and runway_months < 12
        )
        severity = (
            "CRITICAL"
            if viability_critical
            else "WARNING"
            if runway_gap
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "viability_exposure": exposure,
                "business_health_score": round(health if health is not None else 1.0, 4),
                "viability_sensitivity": round(sensitivity, 4),
                "viability_risk": round(
                    1.0 - health if health is not None else 0.0, 4
                ),
                "runway_funnel_suppressor": round(suppressor, 4),
                "explicit_runway_months": float(runway_months or 0),
                "raised_amount_millions": round(total_raised, 4),
            },
            flags={
                "runway_gap": runway_gap,
                "viability_critical": viability_critical,
                "funding_evidence": (
                    breakeven
                    or funding_claim
                    or total_raised > 0.0
                    or runway_months is not None
                ),
                "break_even_reached": breakeven,
                "explicit_runway_reported": runway_months is not None,
            },
            narrative_findings=[
                (
                    f"Viability health: {health:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                    if health is not None
                    else "Viability: not discussed | Funnel suppressor: 1.00"
                ),
                (
                    f"Runway: {runway_months} months | "
                    f"Funding: {total_raised:.2f}M USD-equiv"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("runway_funnel_suppressor", 1.0))
        if suppressor >= _ACTIVE_SUPPRESSOR_THRESHOLD:
            return {}
        return {
            ("CONSIDER", "DECIDE"): max(
                0.05, min(0.95, suppressor)
            ),
        }

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("viability_critical")]
        gaps = [o for o in outputs if o.flags.get("runway_gap")]
        affected = list(
            dict.fromkeys(
                o.cluster_id for o in critical + gaps if o.cluster_id
            )
        )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters face critical cash-runway risk; "
                f"{len(gaps)} clusters with viability gaps"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.03, 3),
            conversion_impact=round(
                len(critical) * 0.045 + len(gaps) * 0.02, 3
            ),
            recommended_action=(
                "Publish concrete funding, revenue and 12-18 month runway "
                "evidence; share unit economics with high-risk, high-ticket "
                "clusters"
            ),
            severity="CRITICAL" if critical else "WARNING" if gaps else "INFO",
        )


__all__ = ["RunwayArchitect"]
