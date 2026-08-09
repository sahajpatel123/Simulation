"""
PlatformDependencyArchitect — external platform, algorithm and API
provider dependence across the 52 consumer clusters.

Startups often die on someone else's roadmap: an app-store approval or
policy change removes the product from discovery, a search or social
algorithm stops sending traffic, an ad platform bans the account, or a
third-party API (LLM provider, cloud, payment gateway) raises prices,
changes terms or goes down. The rest of the engine models distribution
channels, competitive dynamics and regulatory exposure, but has no
dedicated signal for concentration risk on the platforms themselves.

What this architect does:

* **Exposure detection** — scans assumption text for four dependency
  groups: app-store/OS marketplaces (approval, review, commission,
  in-app purchase), search/ad/social algorithms (SEO, ads, influencer
  reach), third-party API/cloud providers (LLM APIs, AWS, Stripe,
  rate limits) and platform policy/lock-in language. Detection is
  negation-aware: "we don't use the app store", "no reliance on any
  cloud provider" and "we are independent of any app store" are
  disclaimers, not dependencies, while pending status ("app store
  approval not yet received") still counts because the founder is
  engaging with the platform. A small baseline keeps funnels neutral
  until the founder actually mentions platform dependence.
* **Concentration modelling** — exposure scales with distrustful,
  risk-averse, low-literacy and socially-oriented clusters, which are
  exactly the segments that abandon a product when a store, algorithm
  or provider becomes unstable. Mentioning one platform with no
  mitigation raises single-channel risk; mentioning several without
  diversifying raises concentration risk.
* **Mitigation credibility** — evidence of owned/alternative channels
  (web app/PWA, email list, direct sales, multi-platform, multi-cloud,
  self-hosting, open source) raises ``mitigation_credibility`` to 1.0,
  softens the funnel suppressor and earns a small purchase-stage
  ``platform_advantage_lift``. Evidence detection is negation- and
  intent-aware: "no web app", "plan to build a PWA" or "vendor
  approval pending" are gaps, never proof, while "No, we already have
  a web app" stays evidence.
* **Markov overrides** — only when platform exposure is active:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + platform_advantage_lift`` when mitigations
  exist.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
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

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_APP_STORE_KEYWORDS: tuple[str, ...] = (
    "app store", "play store", "apple app store", "google play",
    "app store approval", "app store review", "app approval",
    "app review", "in-app purchase", "in-app purchases", "iap",
    "store commission", "30% commission", "app store policy",
    "store listing", "aso", "app store optimization",
)

_SEARCH_ALGO_KEYWORDS: tuple[str, ...] = (
    "search engine", "google search", "seo", "search ranking",
    "algorithm", "organic traffic", "google ads", "facebook ads",
    "meta ads", "instagram ads", "tiktok ads", "influencer",
    "paid acquisition", "ad spend", "social media",
    "recommendation algorithm",
)

_API_PROVIDER_KEYWORDS: tuple[str, ...] = (
    "api provider", "openai", "anthropic", "llm api", "llm provider",
    "aws", "amazon web services", "azure", "google cloud",
    "cloud provider", "stripe", "payment gateway", "twilio",
    "third-party api", "vendor api", "sdk dependency", "rate limits",
    "api quota", "api pricing", "api dependency",
)

_PLATFORM_POLICY_KEYWORDS: tuple[str, ...] = (
    "terms of service", "platform policy", "developer agreement",
    "vendor lock-in", "lock-in", "platform dependency", "platform risk",
    "account suspension", "delisting",
)

_MITIGATION_KEYWORDS: tuple[str, ...] = (
    "web app", "web-first", "web first", "pwa",
    "progressive web app", "own website", "direct sales",
    "email list", "newsletter", "multi-platform", "multi-channel",
    "android and ios", "ios and android", "both platforms",
    "self-hosted", "self-host", "on-prem", "on-premise",
    "open source", "multi-cloud", "byoc", "bring your own cloud",
    "first-party data", "own infrastructure", "owned channels",
    "alternative providers", "multi-vendor", "portable", "exportable",
    "own distribution", "no reliance", "do not rely", "does not rely",
    "not reliant", "not dependent", "do not depend", "does not depend",
    "independent of", "independent from", "not tied to",
    "no lock-in", "no vendor lock-in", "avoid lock-in",
)

# Absence markers that qualify a matched phrase ("no web app", "app
# store approval missing", "PWA not built"). Discourse negation
# ("No, we already have a web app") is handled separately.
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "unavailable", "unreleased", "unsupported",
    "unconfirmed", "pending", "awaiting", "awaited", "outstanding",
    "incomplete", "suspended", "rejected", "denied", "withdrawn",
    "expired", "revoked", "void", "failed",
})

# Aspirational markers: a plan, requirement or roadmap is not evidence.
# "We plan to add a web app", "will build a PWA", "working on a
# multi-cloud setup" describe intent, not a working mitigation.
_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "intend", "intends", "intended", "add",
    "adding", "build", "building", "aim", "aims", "hoping", "hope",
    "hopes", "want", "wants", "wanted", "scheduled", "upcoming", "due",
    "set", "setting", "setup", "integrate", "integrating", "getting",
    "get", "obtain", "obtaining", "pursue", "pursuing", "working on",
    "in progress", "to be",
})

# Contracted negations are expanded before matching so "we don't have a
# web app" and "PWA isn't ready" are gaps, never evidence. The optional
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
_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[.,;:!?—–\n]|\b(?:but|yet|though|although|whereas|however|while)\b",
    re.IGNORECASE,
)

# Neutral baseline so runs that never mention platform dependence stay
# unchanged; explicit signals drive the real exposure.
_EXPOSURE_BASELINE: float = 0.08
_SIGNAL_STEP: float = 0.20
_EXPOSURE_CAP: float = 0.95
_ACTIVE_THRESHOLD: float = 0.15
_MAX_SUPPRESSION: float = 0.35
_SUPPRESSOR_FLOOR: float = 0.55
_MAX_ADVANTAGE_LIFT: float = 0.10
_CRITICAL_RISK: float = 0.55
_WARNING_RISK: float = 0.25


@lru_cache(maxsize=8)
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


# ── Negation-aware exposure detection ───────────────────────────────────
#
# A platform mention is exposure only when the founder is (or plans to
# be) on that platform. "We don't use the app store", "no reliance on
# any cloud provider" and "we are independent of any app store" are
# disclaimers, not dependencies; but status/gate statements ("app store
# approval not yet received", "we don't have app store approval yet")
# still signal engagement with the platform and stay exposure.
_SIGNAL_NEGATORS: frozenset[str] = frozenset({
    "no", "not", "never", "without", "none", "neither",
    "avoid", "avoids", "avoided", "avoiding",
    "stopped", "quit", "ceased",
})

_SIGNAL_DEPENDENCE_VERBS: frozenset[str] = frozenset({
    "use", "uses", "used", "using",
    "rely", "relies", "relied", "relying",
    "depend", "depends", "depended", "depending",
    "need", "needs", "needed", "require", "requires", "required",
    "want", "wants", "wanted",
    "offer", "offers", "offered", "offering",
    "sell", "sells", "sold", "selling",
    "accept", "accepts", "accepted", "accepting",
    "take", "takes", "took", "taking",
    "run", "runs", "ran", "running",
    "host", "hosts", "hosted", "hosting",
    "advertise", "advertises", "advertised", "advertising",
    "build", "builds", "built", "building",
    "integrate", "integrates", "integrated", "integrating",
    "have", "has", "had",
    "pay", "pays", "paid", "paying",
    "ship", "ships", "shipped", "shipping",
    "distribute", "distributes", "distributed", "distributing",
})

_SIGNAL_RELIANCE_NOUNS: frozenset[str] = frozenset({
    "reliance", "dependency", "dependence", "dependencies", "dependences",
    "reliant", "dependent", "tied",
})

# Words that turn a mention into a gate/status statement ("app store
# approval", "search engine rankings", "api quota"). Negating a status
# ("no approval yet") still means the founder is pursuing that platform,
# so those mentions stay exposure — except when the negation explicitly
# removes the need ("we don't need app store approval").
_SIGNAL_GATE_WORDS: frozenset[str] = frozenset({
    "approval", "approvals", "approved", "review", "reviews",
    "policy", "policies", "commission", "commissions",
    "listing", "listings", "rank", "ranks", "ranking", "rankings",
    "quota", "quotas", "limit", "limits", "pricing", "price",
    "suspension", "suspensions", "delisting", "terms",
    "agreement", "agreements", "acceptance", "pending",
    "permission", "permissions", "authorization", "authorisation",
    "certification", "consent", "status",
})

_SIGNAL_QUALIFIERS: frozenset[str] = frozenset({
    "solely", "only", "just", "exclusively", "entirely", "alone",
    "primarily", "mainly", "mostly",
})

# Pending/future markers: "not yet" / "soon" means the founder still
# plans platform engagement, so the mention stays exposure.
_SIGNAL_PENDING_MARKERS: frozenset[str] = frozenset({"yet", "soon"})

_SIGNAL_INDEPENDENCE_PHRASES: tuple[str, ...] = (
    "independent of", "independent from",
    "not tied to", "not dependent on", "not reliant on",
    "no reliance on", "no dependency on", "no dependence on",
    "no longer use", "no longer rely", "no longer depend",
    "not part of",
)

_SIGNAL_AFTER_VOID_PATTERN = re.compile(
    r"\bnot (?:required|needed|necessary|applicable|relevant|part of)\b"
)

_TRAILING_ARTICLE_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "any", "some",
})


def _signal_match_is_voided(
    text: str,
    start: int,
    end: int,
) -> bool:
    """True when a platform mention is an explicit dependence disclaimer."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-12:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    before_text = " ".join(before)
    for article in _TRAILING_ARTICLE_WORDS:
        if before_text.endswith(f" {article}"):
            before_text = before_text[: -len(article) - 1]
            break
    # "we are independent of X" (and variants) can govern a short list:
    # "independent of AWS and Google Cloud". "Not independent of X" is
    # the opposite, so it must never be treated as a disclaimer.
    if not re.search(
        r"\b(?:no longer|not(?:\s+[a-z]+){0,3})\s+independent\b",
        before_text,
    ):
        if any(
            re.search(
                re.escape(phrase) + r"(?:\s+[a-z]+){0,4}$",
                before_text,
            )
            for phrase in _SIGNAL_INDEPENDENCE_PHRASES
        ):
            return True

    pending = bool(_SIGNAL_PENDING_MARKERS & (set(before) | set(after)))
    if not pending and clause_end < len(text):
        # "yet"/"soon" is also a clause-boundary word, so when it is the
        # boundary immediately after the mention it never appears in the
        # after-token window. A trailing "not yet" means platform
        # engagement is still planned, so the mention stays exposure.
        pending = re.match(r"\b(?:yet|soon)\b", text[clause_end:]) is not None
    if pending:
        return False

    if not before:
        # Post-posed disclaimer: "app store is not part of our strategy",
        # "approval is not required for our model".
        if after and _SIGNAL_AFTER_VOID_PATTERN.search(" ".join(after)):
            return True
        return False

    neg_positions = [
        i for i, token in enumerate(before)
        if token in _SIGNAL_NEGATORS
        and not any(
            before[j] == "independent"
            for j in range(i + 1, min(i + 4, len(before)))
        )
    ]
    if not neg_positions:
        return False

    # "not only/just/merely/simply" focus presupposes the mention and
    # never voids it by itself ("not only the app store but also...").
    neg_positions = [
        i for i in neg_positions
        if not (
            i + 1 < len(before)
            and before[i + 1] in _DISCOURSE_FOCUS_MARKERS
        )
    ]
    if not neg_positions:
        return False

    gate_after = any(token in _SIGNAL_GATE_WORDS for token in after[:3])
    reliance_words = set(before) & _SIGNAL_RELIANCE_NOUNS
    verb_positions = [
        i for i, token in enumerate(before)
        if token in _SIGNAL_DEPENDENCE_VERBS
    ]

    for neg_pos in neg_positions:
        # Direct disclaimer: "no app store", "without the app store",
        # "we avoid the app store". Gate words protect have-style status
        # statements ("we don't have app store approval").
        if len(before) - neg_pos <= 3:
            have_style = any(
                before[verb_pos] in {"have", "has", "had"}
                for verb_pos in verb_positions
            )
            if not (gate_after and have_style):
                return True
        # Bare disclaimers can also govern a short list: "avoid the app
        # store and Google Play", "no app store or Play Store presence".
        if (
            len(before) - neg_pos <= 6
            and not any(verb_pos >= neg_pos for verb_pos in verb_positions)
            and not reliance_words
            and not any(
                qualifier in _SIGNAL_QUALIFIERS
                for qualifier in before[neg_pos:]
            )
        ):
            have_style = any(
                before[verb_pos] in {"have", "has", "had"}
                for verb_pos in verb_positions
            )
            if not (gate_after and have_style):
                return True
        # Negated dependence verb in the same window: "we do not use the
        # app store", "don't rely on Google ads", "stopped shipping IAPs".
        for verb_pos in verb_positions:
            if (
                abs(verb_pos - neg_pos) <= 6
                and len(before) - max(neg_pos, verb_pos) <= 6
            ):
                if any(
                    qualifier in _SIGNAL_QUALIFIERS
                    for qualifier in before[min(neg_pos, verb_pos):]
                ):
                    # "not rely solely on X" / "don't depend only on X"
                    # still means partial dependence — keep the mention.
                    continue
                if gate_after and before[verb_pos] in {"have", "has", "had"}:
                    continue
                return True
        if reliance_words:
            return True

    return False


def _has_signal(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
) -> bool:
    """Keyword presence after voiding explicit dependence disclaimers."""
    pattern = _keyword_pattern(keywords)
    for text in _assumption_texts(assumptions):
        for match in pattern.finditer(text):
            if not _signal_match_is_voided(text, match.start(), match.end()):
                return True
    return False


# "not only"/"not just" (and variants) are discourse-focus constructions:
# they presuppose the matched phrase ("not just a web app" means the web
# app counts) instead of voiding it. Plain "not" remains a voiding marker.
_DISCOURSE_FOCUS_MARKERS: frozenset[str] = frozenset({
    "only", "just", "merely", "simply",
})


def _is_discourse_negation(tokens: list[str]) -> bool:
    """True for "not only"/"not just" focus constructions."""
    return any(
        tokens[i] == "not"
        and i + 1 < len(tokens)
        and tokens[i + 1] in _DISCOURSE_FOCUS_MARKERS
        for i in range(len(tokens) - 1)
    )


def _match_is_voided(
    text: str,
    start: int,
    end: int,
) -> bool:
    """True when negation or intent markers qualify an evidence match."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    if after and after[0] in {"and", "or", "then", "also", "plus", "too"}:
        after = []
    before_text = " ".join(before)
    after_text = " ".join(after)
    combined = before + after
    # Progress/intent phrases void even under a "not only/just" focus
    # construction: "not only working on a PWA" is still not evidence.
    if any(
        phrase in f"{before_text} {after_text}"
        for phrase in ("working on", "in progress", "to be")
    ):
        return True
    if _is_discourse_negation(combined):
        negation_voided = False
    else:
        negation_voided = bool(set(combined) & _NEGATION_MARKERS)
    return negation_voided or bool(set(combined) & _INTENT_MARKERS)


def _has_evidence(assumptions: list[dict[str, Any]] | None) -> bool:
    """True when any mitigation evidence survives negation/intent guards."""
    pattern = _keyword_pattern(_MITIGATION_KEYWORDS)
    for text in _assumption_texts(assumptions):
        for match in pattern.finditer(text):
            if not _match_is_voided(text, match.start(), match.end()):
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


class PlatformDependencyArchitect(BaseArchitect):
    """Evaluates app-store, algorithm and API-provider dependence risk."""

    @property
    def name(self) -> str:
        return "PlatformDependencyArchitect"

    @property
    def product_types(self) -> list[str]:
        # Digital products whose discovery, distribution or runtime sits
        # on an external platform. Hardware categories are excluded:
        # their platform risk is already modelled by ecosystem and
        # distribution architects.
        return [
            "mobile_app", "consumer_app", "marketplace", "b2b_marketplace",
            "developer_tool", "saas", "productivity_tool", "d2c",
        ]

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
        social = _trait(traits, "social_orientation")

        app_store_signal = _has_signal(assumptions, _APP_STORE_KEYWORDS)
        search_algo_signal = _has_signal(assumptions, _SEARCH_ALGO_KEYWORDS)
        api_signal = _has_signal(assumptions, _API_PROVIDER_KEYWORDS)
        policy_signal = _has_signal(assumptions, _PLATFORM_POLICY_KEYWORDS)
        evidence = _has_evidence(assumptions)

        mentioned = sum(
            bool(sig)
            for sig in (
                app_store_signal,
                search_algo_signal,
                api_signal,
                policy_signal,
            )
        )
        exposure = round(
            min(_EXPOSURE_CAP, _EXPOSURE_BASELINE + mentioned * _SIGNAL_STEP),
            4,
        )
        concentration = round(mentioned / 4.0, 4)
        active = exposure > _ACTIVE_THRESHOLD or (
            evidence and mentioned > 0
        )

        credibility = (
            1.0 if evidence else max(0.10, 1.0 - exposure * 0.90)
        )
        credibility = round(_clamp(credibility), 4)

        # Single-channel risk: one platform mentioned with no owned or
        # alternative channel is the classic "we live and die by X" trap.
        single_channel_risk = round(
            _clamp(concentration * (0.30 + 0.70 * (1.0 - credibility))),
            4,
        )

        # Gate risk: the strongest unmitigated dependency, reduced but
        # not eliminated by credible mitigations.
        gate_level = 0.0
        if app_store_signal and not evidence:
            gate_level = max(gate_level, 0.70)
        if search_algo_signal and not evidence:
            gate_level = max(gate_level, 0.55)
        if api_signal and not evidence:
            gate_level = max(gate_level, 0.45)
        gate_risk = round(
            gate_level * (0.55 + 0.45 * (1.0 - credibility)),
            4,
        )

        # Distrustful, risk-averse, low-literacy and socially-driven
        # clusters abandon a product whose availability is at the mercy
        # of someone else's platform.
        cluster_blend = (
            0.35 * (1.0 - trust)
            + 0.30 * risk_av
            + 0.20 * (1.0 - literacy)
            + 0.15 * social
        )
        base_risk = exposure * (0.30 + 0.75 * cluster_blend)
        platform_risk = round(
            _clamp(
                base_risk * 0.55
                + single_channel_risk * 0.30
                + gate_risk * 0.30
            ),
            4,
        )

        if not active:
            suppressor = 1.0
        else:
            raw_suppression = platform_risk * (
                0.85 if not evidence else 0.55
            )
            suppressor = round(
                _clamp(
                    1.0 - min(_MAX_SUPPRESSION, raw_suppression),
                    _SUPPRESSOR_FLOOR,
                    1.0,
                ),
                4,
            )

        lift = (
            round(min(_MAX_ADVANTAGE_LIFT, exposure * 0.08), 4)
            if evidence and active and mentioned > 0
            else 0.0
        )

        app_store_gate = active and app_store_signal and not evidence
        algorithm_dependency = active and search_algo_signal and not evidence
        api_concentration = active and api_signal and not evidence
        single_dependency = active and mentioned == 1 and not evidence

        severity = (
            "CRITICAL"
            if active and not evidence and platform_risk >= _CRITICAL_RISK
            else "WARNING"
            if active
            and (
                app_store_gate
                or algorithm_dependency
                or api_concentration
                or single_dependency
                or platform_risk >= _WARNING_RISK
            )
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "platform_dependency_exposure": exposure,
                "dependency_concentration":     concentration,
                "single_channel_risk":          single_channel_risk,
                "platform_gate_risk":           gate_risk,
                "platform_risk_score":          platform_risk,
                "platform_risk_suppressor":     suppressor,
                "platform_advantage_lift":      lift,
                "mitigation_credibility":       credibility,
            },
            flags={
                "app_store_gate":                app_store_gate,
                "algorithm_dependency":          algorithm_dependency,
                "api_provider_concentration":    api_concentration,
                "platform_single_dependency":    single_dependency,
                "platform_mitigation_advantage": active and evidence,
            },
            narrative_findings=[
                (
                    f"Platform exposure: {exposure:.2f} | "
                    f"Concentration: {concentration:.2f} | "
                    f"Single-channel: {single_channel_risk:.2f}"
                ),
                (
                    f"Gate risk: {gate_risk:.2f} | "
                    f"Risk: {platform_risk:.2f} | "
                    f"Suppressor: {suppressor:.2f} | "
                    f"Evidence: {evidence}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        exposure = float(
            output.metrics.get("platform_dependency_exposure", 0.0)
        )
        if exposure <= _ACTIVE_THRESHOLD:
            return {}
        suppressor = float(output.metrics.get("platform_risk_suppressor", 1.0))
        lift = float(output.metrics.get("platform_advantage_lift", 0.0))
        overrides: dict[tuple[str, str], float] = {}
        if suppressor < 1.0:
            overrides[("BROWSE", "CONSIDER")] = _clamp(
                suppressor, _SUPPRESSOR_FLOOR, 0.999
            )
            overrides[("CONSIDER", "DECIDE")] = _clamp(
                suppressor + 0.05, _SUPPRESSOR_FLOOR + 0.05, 0.999
            )
        if lift > 0.0:
            overrides[("DECIDE", "PURCHASE")] = _clamp(
                1.0 + lift, 0.55, 1.15
            )
        return overrides

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        critical = [
            o for o in outputs if o.severity == "CRITICAL"
        ]
        warning = [
            o for o in outputs
            if o.severity == "WARNING"
            and (
                o.flags.get("app_store_gate")
                or o.flags.get("algorithm_dependency")
                or o.flags.get("api_provider_concentration")
                or o.flags.get("platform_single_dependency")
            )
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No platform dependency blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting owned/alternative channels and "
                    "multi-provider fallbacks as the product scales"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters critically exposed to platform "
                f"dependence; {len(warning)} at risk from store, algorithm "
                f"or API concentration"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.05 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Diversify distribution and infrastructure: web-first/PWA "
                "access, owned email list, multi-channel acquisition and "
                "multi-cloud/API fallbacks so no single store, algorithm "
                "or provider can kill the funnel"
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["PlatformDependencyArchitect"]
