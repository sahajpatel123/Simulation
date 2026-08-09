"""
BehavioralEconomicsArchitect — decision-heuristic and behavioural-bias evaluation.

Why it exists
-------------
TheCee's architect stack already models price, trust, messaging clarity, AI
skepticism and cultural context, but nothing in the funnel directly accounts
for the behavioural heuristics that dominate real purchase decisions: loss
aversion, social proof, choice overload, scarcity/urgency, default bias and
anchoring. A pitch can be affordable, credible and clear and still lose
buyers because it triggers decision fatigue or fails to de-risk the final
commitment. This architect scores those heuristics per cluster so founders
see exactly which behavioural lever their pitch is missing.

What this architect does
------------------------
* **Signal extraction** — reads the project description plus scored
  assumption texts and scores six evidence classes:
  - *risk reversal*: money-back guarantee, free trial, refund, cancel
    anytime, warranty...
  - *social proof*: review counts, testimonials, case studies, user scale,
    press/awards...
  - *choice simplicity*: one-plan/simple pricing versus plan tiers, bundles,
    add-ons...
  - *scarcity/urgency*: limited time/stock, early bird, launch offer...
  - *default bias*: pre-selected, auto-renew, opt-out, trial auto-converts...
  - *anchoring*: was-now pricing, % off, "worth ₹", compare-at...
* **Bias modelling** — combines evidence with cluster traits: risk aversion
  plus low trust drive loss aversion; social orientation plus low trust drive
  social-proof weight; low digital literacy amplifies choice overload and
  default-bias exposure; price sensitivity amplifies anchoring.
* **Funnel effects** — risk reversal lifts DECIDE→PURCHASE; social proof and
  anchoring lift BROWSE→CONSIDER; choice overload suppresses
  CONSIDER→DECIDE; urgency lifts CONSIDER→DECIDE unless it backfires on
  risk-averse, low-trust clusters.
* **Founder insight** — the cross-cluster report names the dominant missing
  behavioural lever and tells the founder which mechanism to add.

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
from app.simulation.clusters.registry import ClusterRegistry

# ── Model constants ─────────────────────────────────────────────────────

_ACTIVE_RISK_THRESHOLD: float = 0.55
_ACTIVE_OVERLOAD_THRESHOLD: float = 0.55
_ACTIVE_DEFAULT_BIAS_THRESHOLD: float = 0.55
_EVIDENCE_SUFFICIENT: float = 0.6
_SUPPRESSOR_FLOOR: float = 0.55
_SEVERITY_CRITICAL_FLAGS: int = 3


# ── Evidence vocabularies ───────────────────────────────────────────────

# Each tuple is one evidence class; a class is "covered" when any of its
# phrases appears in the pitch. Coverage score = 0.0 / 0.3 / 0.6 / 0.9 by
# number of covered classes, so repetition never inflates the evidence.
_RISK_REVERSAL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("money-back", "money back", "guarantee", "guaranteed", "risk-free",
     "risk free", "no risk"),
    ("free trial", "trial period", "free month", "first month free",
     "freemium"),
    ("refund", "refunds", "returns", "30-day return", "15-day return",
     "7-day return", "return policy"),
    ("cancel anytime", "no lock-in", "no lock in", "warranty",
     "extended warranty"),
)

_SOCIAL_PROOF_GROUPS: tuple[tuple[str, ...], ...] = (
    ("reviews", "ratings", "rated", "rating"),
    ("testimonials", "testimonial", "case study", "case studies",
     "success stories"),
    ("users", "customers", "downloads", "subscribers", "waitlist",
     "waiting list"),
    ("featured in", "covered by", "press", "award-winning", "award winning",
     "trusted by", "accredited"),
)

_CHOICE_SIMPLICITY_KEYWORDS: tuple[str, ...] = (
    "one plan", "single plan", "simple pricing", "one price", "all-in-one",
    "no hidden fees", "clear pricing", "one subscription", "flat pricing",
)

_CHOICE_COMPLEXITY_KEYWORDS: tuple[str, ...] = (
    "plans", "tiers", "bundles", "add-ons", "add ons", "options",
    "choose from", "customize", "configurable", "many features",
    "feature matrix",
)

_SCARCITY_KEYWORDS: tuple[str, ...] = (
    "limited time", "limited stock", "last chance", "only a few",
    "early bird", "expires", "today only", "flash sale", "launch offer",
    "while supplies last",
)

_DEFAULT_BIAS_KEYWORDS: tuple[str, ...] = (
    "pre-selected", "preselected", "auto-enroll", "auto enroll",
    "auto-renew", "auto renew", "automatic renewal", "opt-out", "opt out",
    "default plan", "default option", "starts automatically",
    "trial converts automatically", "set and forget",
)

_ANCHORING_KEYWORDS: tuple[str, ...] = (
    "was rs", "was inr", "was $", "was ₹",
    "now rs", "now inr", "now $", "now ₹",
    "worth rs", "worth inr", "worth $", "worth ₹",
    "compared to", "compare at", "retail price", "marked down",
    "save 50", "save 30", "save 20", "% off", "discount",
    "strike-through", "strikethrough",
)

_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "without", "non", "lack", "lacks",
    "lacking", "missing", "absent", "unclear",
})
_CLAUSE_BOUNDARIES: tuple[str, ...] = (".", ",", ";", ":", "!", "?", "—", "–", "\n")


@lru_cache(maxsize=64)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


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
        texts.append(raw.lower())
    description = (env_params or {}).get("description", "")
    if description is not None:
        description = str(description).strip()
        if description:
            texts.append(description.lower())
    return list(dict.fromkeys(texts))


def _count_matches(text: str, keywords: tuple[str, ...]) -> int:
    """Count keyword matches, ignoring matches negated in the same clause.

    "no money-back guarantee" or "without a free trial" is a gap, not
    evidence, so a negation marker in the preceding or following four words
    of the clause voids the match. Self-contained positive phrases like
    "no risk" and "no lock-in" are unaffected because the marker is part
    of the keyword itself.
    """
    pattern = _keyword_pattern(keywords)
    count = 0
    for match in pattern.finditer(text):
        clause_start = 0
        for char in _CLAUSE_BOUNDARIES:
            idx = text.rfind(char, 0, match.start())
            if idx > clause_start:
                clause_start = idx + 1
        clause_end = len(text)
        for char in _CLAUSE_BOUNDARIES:
            idx = text.find(char, match.end())
            if idx != -1 and idx < clause_end:
                clause_end = idx
        before = re.findall(
            r"[a-z]+", text[clause_start:match.start()]
        )[-4:]
        after = re.findall(
            r"[a-z]+", text[match.end():clause_end]
        )[:4]
        if set(before) & _NEGATION_MARKERS or set(after) & _NEGATION_MARKERS:
            continue
        count += 1
    return count


def _covered_groups(text: str, groups: tuple[tuple[str, ...], ...]) -> int:
    """Number of evidence classes with at least one keyword match."""
    return sum(1 for group in groups if _count_matches(text, group) > 0)


def _evidence_score(covered_classes: int) -> float:
    """Map evidence-class coverage to a 0.0/0.3/0.6/0.9 score."""
    return {0: 0.0, 1: 0.3, 2: 0.6, 3: 0.9}.get(covered_classes, 0.9)


class BehavioralEconomicsArchitect(BaseArchitect):
    """Evaluates decision heuristics and behavioural biases per cluster."""

    @property
    def name(self) -> str:
        return "BehavioralEconomicsArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Decision heuristics shape every purchase funnel.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        risk_aversion = _trait(traits, "risk_aversion")
        trust = _trait(traits, "trust")
        literacy = _trait(traits, "digital_literacy")
        social = _trait(traits, "social_orientation")
        price_sens = _trait(traits, "price_sensitivity")
        patience = _trait(traits, "patience_score")

        texts = _collect_texts(assumptions, env_params)
        joined = "\n".join(texts)

        # ── Evidence extraction ──────────────────────────────────────────
        risk_reversal_covered = _covered_groups(joined, _RISK_REVERSAL_GROUPS)
        social_proof_covered = _covered_groups(joined, _SOCIAL_PROOF_GROUPS)
        risk_reversal = _evidence_score(risk_reversal_covered)
        social_proof = _evidence_score(social_proof_covered)

        simple_matches = _count_matches(joined, _CHOICE_SIMPLICITY_KEYWORDS)
        complex_matches = _count_matches(joined, _CHOICE_COMPLEXITY_KEYWORDS)
        scarcity_matches = _count_matches(joined, _SCARCITY_KEYWORDS)
        default_matches = _count_matches(joined, _DEFAULT_BIAS_KEYWORDS)
        anchor_matches = _count_matches(joined, _ANCHORING_KEYWORDS)

        # ── Trait-driven sensitivities ───────────────────────────────────
        loss_aversion = _clamp(
            0.15 + 0.45 * risk_aversion + 0.20 * (1.0 - trust),
            low=0.15,
            high=0.90,
        )
        social_proof_weight = _clamp(
            0.10 + 0.50 * social + 0.25 * (1.0 - trust),
            low=0.15,
            high=0.90,
        )
        choice_overload_risk = _clamp(
            (1.0 - literacy) * 0.40
            + risk_aversion * 0.15
            + (1.0 - patience) * 0.10
            + (0.25 if complex_matches > simple_matches else 0.0),
            low=0.05,
            high=0.95,
        )
        choice_simplicity_evidence = _clamp(
            0.65
            + 0.20 * min(simple_matches, 2)
            - 0.25 * min(complex_matches, 2),
            low=0.05,
            high=0.95,
        )
        scarcity_pressure = _clamp(
            0.15 + 0.30 * min(scarcity_matches, 3),
            low=0.05,
            high=0.95,
        )
        scarcity_backfire = (
            scarcity_pressure >= 0.45
            and risk_aversion > 0.65
            and trust < 0.40
        )
        default_bias_exposure = _clamp(
            0.10
            + 0.25 * min(default_matches, 2)
            + (1.0 - literacy) * 0.20,
            low=0.05,
            high=0.95,
        )
        anchoring_effectiveness = _clamp(
            0.35 * min(anchor_matches, 2)
            + (0.10 if anchor_matches else 0.0)
            + 0.15 * price_sens * min(anchor_matches, 1),
            low=0.0,
            high=0.90,
        )

        # ── Perceived risk & social-proof coverage ───────────────────────
        perceived_purchase_risk = _clamp(
            loss_aversion * (1.0 - 0.70 * risk_reversal),
            low=0.05,
            high=0.95,
        )
        social_proof_coverage = _clamp(
            0.25 * social_proof_weight + 0.75 * social_proof,
            low=0.05,
            high=0.95,
        )

        # ── Funnel suppressor ────────────────────────────────────────────
        suppressor = 1.0
        if perceived_purchase_risk >= _ACTIVE_RISK_THRESHOLD and risk_reversal < _EVIDENCE_SUFFICIENT:
            suppressor -= 0.20 * min(
                1.0,
                (perceived_purchase_risk - _ACTIVE_RISK_THRESHOLD) / 0.30,
            )
        if choice_overload_risk >= _ACTIVE_OVERLOAD_THRESHOLD:
            suppressor -= 0.14 * min(
                1.0,
                (choice_overload_risk - _ACTIVE_OVERLOAD_THRESHOLD) / 0.30,
            )
        if scarcity_backfire:
            suppressor -= 0.12
        if default_bias_exposure >= _ACTIVE_DEFAULT_BIAS_THRESHOLD:
            suppressor -= 0.08
        suppressor = round(_clamp(suppressor, low=_SUPPRESSOR_FLOOR), 4)

        # ── Flags & severity ─────────────────────────────────────────────
        flags = {
            "risk_reversal_missing": (
                perceived_purchase_risk >= _ACTIVE_RISK_THRESHOLD
                and risk_reversal < _EVIDENCE_SUFFICIENT
            ),
            "social_proof_deficit": (
                social_proof_weight > 0.55
                and social_proof < _EVIDENCE_SUFFICIENT
            ),
            "choice_overload_active": (
                choice_overload_risk >= _ACTIVE_OVERLOAD_THRESHOLD
            ),
            "scarcity_backfire_risk": scarcity_backfire,
            "default_bias_concern": (
                default_bias_exposure >= _ACTIVE_DEFAULT_BIAS_THRESHOLD
            ),
            "behavioral_suppression_active": suppressor < 1.0,
        }
        substantive_flags = [
            "risk_reversal_missing",
            "social_proof_deficit",
            "choice_overload_active",
            "scarcity_backfire_risk",
            "default_bias_concern",
        ]
        active_flag_count = sum(1 for key in substantive_flags if flags[key])
        severity = (
            "CRITICAL"
            if active_flag_count >= _SEVERITY_CRITICAL_FLAGS
            else "WARNING"
            if active_flag_count >= 1
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "loss_aversion_sensitivity": round(loss_aversion, 4),
                "risk_reversal_evidence": round(risk_reversal, 4),
                "perceived_purchase_risk": round(perceived_purchase_risk, 4),
                "social_proof_weight": round(social_proof_weight, 4),
                "social_proof_evidence": round(social_proof, 4),
                "social_proof_coverage": round(social_proof_coverage, 4),
                "choice_simplicity_evidence": round(
                    choice_simplicity_evidence, 4
                ),
                "choice_overload_risk": round(choice_overload_risk, 4),
                "scarcity_pressure": round(scarcity_pressure, 4),
                "anchoring_effectiveness": round(anchoring_effectiveness, 4),
                "default_bias_exposure": round(default_bias_exposure, 4),
                "behavioral_funnel_suppressor": suppressor,
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Loss aversion: {loss_aversion:.2f} | "
                    f"Perceived purchase risk: {perceived_purchase_risk:.2f} "
                    f"| Risk reversal evidence: {risk_reversal:.2f}"
                ),
                (
                    f"Social proof weight: {social_proof_weight:.2f} | "
                    f"Choice overload: {choice_overload_risk:.2f} | "
                    f"Default-bias exposure: {default_bias_exposure:.2f}"
                ),
                (
                    f"Scarcity: {scarcity_pressure:.2f} | "
                    f"Anchoring: {anchoring_effectiveness:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("behavioral_funnel_suppressor", 1.0))
        social = float(output.metrics.get("social_proof_evidence", 0.0))
        anchoring = float(output.metrics.get("anchoring_effectiveness", 0.0))
        overload = float(output.metrics.get("choice_overload_risk", 0.2))
        scarcity = float(output.metrics.get("scarcity_pressure", 0.15))
        backfire = bool(output.flags.get("scarcity_backfire_risk", False))
        risk_reversal = float(output.metrics.get("risk_reversal_evidence", 0.0))
        default_bias = float(output.metrics.get("default_bias_exposure", 0.0))

        has_evidence = (
            social > 0.0
            or anchoring > 0.0
            or risk_reversal > 0.0
            or scarcity > 0.15
            or default_bias > 0.25
            or overload >= _ACTIVE_OVERLOAD_THRESHOLD
            or suppressor < 1.0
        )
        if not has_evidence:
            return {}

        urgency_boost = scarcity if not backfire else 0.0
        return {
            ("BROWSE", "CONSIDER"): round(
                _clamp(0.70 + 0.25 * social + 0.15 * anchoring, 0.55, 1.25),
                4,
            ),
            ("CONSIDER", "DECIDE"): round(
                _clamp(
                    0.90 - 0.25 * overload + 0.15 * urgency_boost,
                    0.45,
                    1.25,
                ),
                4,
            ),
            ("DECIDE", "PURCHASE"): round(
                _clamp(suppressor, low=_SUPPRESSOR_FLOOR, high=0.999),
                4,
            ),
        }

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        if not outputs:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No behavioural-economics outputs to aggregate"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Re-run simulation with at least one cluster"
                ),
                severity="INFO",
            )

        registry = ClusterRegistry()
        total_weight = (
            sum(c.population_weight for c in registry.all_clusters()) or 1.0
        )

        risk_missing = [
            o for o in outputs if o.flags.get("risk_reversal_missing")
        ]
        proof_deficit = [
            o for o in outputs if o.flags.get("social_proof_deficit")
        ]
        overloaded = [
            o for o in outputs if o.flags.get("choice_overload_active")
        ]
        scarcity_risk = [
            o for o in outputs if o.flags.get("scarcity_backfire_risk")
        ]
        default_concern = [
            o for o in outputs if o.flags.get("default_bias_concern")
        ]

        affected = list(dict.fromkeys(
            o.cluster_id
            for o in (
                risk_missing
                + proof_deficit
                + overloaded
                + scarcity_risk
                + default_concern
            )
            if o.cluster_id
        ))
        affected_weight = 0.0
        fallback_weight = 1.0 / max(1, len(registry.all_clusters()))
        for cid in affected:
            try:
                cluster = registry.get_cluster(cid)
            except KeyError:
                cluster = None
            if cluster:
                affected_weight += cluster.population_weight
            else:
                affected_weight += fallback_weight
        population_fraction = round(affected_weight / total_weight, 4)

        primary = (
            f"{len(risk_missing)} clusters lack risk reversal; "
            f"{len(overloaded)} face choice overload; "
            f"{len(scarcity_risk)} distrust scarcity pressure; "
            f"{len(proof_deficit)} need more social proof; "
            f"{len(default_concern)} are exposed to default-bias surprise"
        )

        issue_buckets: list[tuple[int, str, str]] = [
            (
                len(risk_missing),
                "risk reversal",
                "Add a money-back guarantee, free trial, refund policy or "
                "cancel-anytime commitment",
            ),
            (
                len(overloaded),
                "choice overload",
                "Cut the plan/option count and add a default recommended "
                "option",
            ),
            (
                len(scarcity_risk),
                "scarcity backfire",
                "Replace aggressive limited-time pressure with value-based "
                "urgency for risk-averse, low-trust segments",
            ),
            (
                len(proof_deficit),
                "social proof",
                "Add segment-specific reviews, testimonials, case studies "
                "or user counts",
            ),
            (
                len(default_concern),
                "default bias",
                "Make renewal and trial conversion explicit opt-in; avoid "
                "surprise auto-charges",
            ),
        ]
        issue_buckets.sort(key=lambda bucket: bucket[0], reverse=True)
        if issue_buckets[0][0] > 0:
            recommended_action = issue_buckets[0][2]
        else:
            recommended_action = (
                "No dominant behavioural blocker detected; keep current "
                "decision-heuristic strategy"
            )

        return DomainReport(
            architect_name=self.name,
            primary_finding=primary,
            affected_cluster_ids=affected,
            population_fraction=population_fraction,
            conversion_impact=round(
                len(risk_missing) * 0.04
                + len(overloaded) * 0.025
                + len(scarcity_risk) * 0.03
                + len(proof_deficit) * 0.02
                + len(default_concern) * 0.015,
                4,
            ),
            recommended_action=recommended_action,
            severity=(
                "CRITICAL"
                if len(risk_missing) + len(scarcity_risk) >= 3
                else "WARNING"
                if affected
                else "INFO"
            ),
        )


__all__ = ["BehavioralEconomicsArchitect"]
