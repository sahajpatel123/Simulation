"""
AccessibilityInclusionArchitect — disability, language, age and literacy
inclusion exposure across the 52 consumer clusters.

Startups leak conversions when the product assumes a "default" user:
screen-reader users cannot complete checkout, deaf users miss audio-only
onboarding, older buyers bounce from dense text, and non-native speakers
abandon English-only flows. The rest of the engine models price, trust,
distribution and cultural fit, but has no dedicated signal for whether the
founder's own assumptions address accessibility and inclusion.

What this architect does:

* **Signal detection** — scans assumption text for four inclusion signal
  groups (disability access, language/localization, age-friendly design,
  low-literacy/beginner support). The product type contributes a small
  contextual baseline only; explicit signals drive the real gap so funnels
  stay unchanged for runs that never mention inclusion.
* **Barrier modelling** — disability barrier scales with low digital
  literacy, risk aversion and older age brackets; language barrier scales
  with low literacy, age and consumer-facing product intensity; age friction
  scales with senior demographics and low literacy.
* **Credibility** — inclusion evidence markers (WCAG/ADA compliance,
  screen-reader support, captions, translation, alt text, inclusive design,
  senior-friendly onboarding, ...) raise ``accessibility_credibility`` to
  1.0, soften the funnel suppressor and earn a small purchase-stage
  ``inclusive_advantage_lift``. Detection is negation- and intent-aware:
  "not yet accessible", "no captions", "unclear WCAG status", "plan to
  translate" or "need to add alt text" are treated as gaps, never evidence.
* **Markov overrides** — only when the inclusion gap is active:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + inclusive_advantage_lift`` when evidence exists.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_DISABILITY_KEYWORDS: tuple[str, ...] = (
    "accessibility", "accessible", "screen reader", "screen-reader",
    "voiceover", "voice-over", "narrator", "wcag", "section 508", "ada",
    "alt text", "alternative text", "captions", "captioning", "subtitles",
    "sign language", "braille", "keyboard navigation", "keyboard accessible",
    "high contrast", "colour contrast", "color contrast", "dyslexia",
    "low vision", "visual impairment", "hearing impairment",
    "hard of hearing", "deaf", "motor impairment", "one-handed",
    "assistive technology", "disability", "disabled users",
    "inclusive design", "universal design", "accessible design",
)

_LANGUAGE_KEYWORDS: tuple[str, ...] = (
    "translation", "translate", "localization", "localisation", "localize",
    "localise", "multilingual", "multi-language", "multiple languages",
    "regional language", "regional languages", "language support",
    "hindi", "tamil", "bengali", "marathi", "telugu", "kannada",
    "malayalam", "gujarati", "punjabi", "urdu", "vernacular",
    "english-only", "english only",
)

_AGE_KEYWORDS: tuple[str, ...] = (
    "elderly", "older users", "older adults", "senior citizens", "seniors",
    "aging population", "ageing population", "retirees", "grandparents",
    "over 60", "over 55", "60 and above", "55 and above", "65 and above",
    "large text", "easy to read",
)

_LITERACY_KEYWORDS: tuple[str, ...] = (
    "low digital literacy", "digital literacy", "first-time smartphone",
    "first time smartphone", "beginner friendly", "beginner-friendly",
    "simple interface", "simple mode", "voice guidance", "voice-first",
    "guided onboarding", "step-by-step", "step by step", "tutorial",
    "non-technical users", "non technical users", "easy mode",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "wcag", "section 508 compliant", "ada compliant", "accessible design",
    "screen reader support", "screen-reader support", "voiceover support",
    "keyboard accessible", "keyboard navigation support", "captioning",
    "captioned", "subtitled", "alt text", "alternative text",
    "high contrast mode", "color contrast compliant",
    "colour contrast compliant", "assistive technology support",
    "accessibility audit", "accessibility testing",
    "accessibility statement", "inclusive design", "universal design",
    "localized", "localised", "translated", "translation support",
    "language support", "multilingual support", "multi-language support",
    "hindi support", "tamil support", "regional language support",
    "vernacular support", "senior friendly", "senior-friendly",
    "beginner friendly", "beginner-friendly", "simple mode", "easy mode",
    "voice guidance", "guided mode", "large text mode", "accessibility mode",
)

# Negation / absence / intent markers that void an evidence keyword when
# they appear within a few words of the match. Aspirational language ("we
# plan to add captions", "must be WCAG compliant") is a gap, not proof.
_GAP_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "pending", "awaiting", "awaited", "outstanding",
    "incomplete", "suspended", "expired", "revoked", "rejected", "denied",
    "withdrawn", "plan", "planned", "planning", "roadmap", "future",
    "eventually", "todo", "need", "needs", "needed", "require", "requires",
    "required", "must", "should", "will", "going to", "intend", "intends",
    "intended", "add", "adding", "build", "building",
})

# Neutral baseline so runs that never mention inclusion stay unchanged.
_BASELINE_GAP: float = 0.05
_GROUP_GAP_STEP: float = 0.25
_GAP_CAP: float = 0.95
_ACTIVE_THRESHOLD: float = 0.15
_EVIDENCE_GAP_MULTIPLIER: float = 0.45
_SUPPRESSOR_MIN: float = 0.55
_SUPPRESSOR_MAX_DROP: float = 0.35
_MAX_ADVANTAGE_LIFT: float = 0.12

# How much language matters for the product category (consumer-facing and
# content-heavy products lose more when flows are single-language).
_LANGUAGE_INTENSITY: dict[str, float] = {
    "d2c": 1.0,
    "marketplace": 1.0,
    "consumer_app": 1.0,
    "mobile_app": 1.0,
    "consumer_hardware": 1.0,
    "smart_home": 1.0,
    "wearable": 1.0,
    "iot_hardware": 0.9,
    "b2b_marketplace": 0.9,
    "health_hardware": 0.8,
    "productivity_tool": 0.7,
    "enterprise_software": 0.7,
    "saas": 0.65,
    "b2b_hardware": 0.7,
    "developer_tool": 0.5,
}


def _has_any_keyword(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
    *,
    guard_negation: bool = False,
) -> bool:
    """
    True when any assumption text contains any keyword (word-boundary).

    With ``guard_negation``, a match is ignored when negation/absence/intent
    markers appear within a few words around it, so "no captions" or "plan
    to localize" never counts as inclusion evidence.
    """
    if not assumptions:
        return False
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )
    for assumption in assumptions:
        if isinstance(assumption, dict):
            text = str(
                assumption.get("text", assumption.get("assumption", ""))
            ).lower()
        else:
            text = str(assumption).lower()
        if not guard_negation:
            if pattern.search(text):
                return True
            continue
        for match in pattern.finditer(text):
            if not _is_gapped(text, match.start(), match.end()):
                return True
    return False


def _is_gapped(text: str, start: int, end: int) -> bool:
    """True when a gap/intent marker sits within ~5 words of a match."""
    before = re.findall(r"[a-z]+", text[max(0, start - 120):start])[-5:]
    after = re.findall(r"[a-z]+", text[end:end + 120])[:5]
    return bool(set(before + after) & _GAP_MARKERS)


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


def _age_seniority(profile: dict[str, Any] | None) -> float:
    """Return 0..1 seniority from an age_bracket like '28-42' or '60-75'."""
    if not isinstance(profile, dict):
        return 0.0
    raw = str(profile.get("age_bracket", "")).strip()
    parts = re.findall(r"\d+", raw)
    if not parts:
        return 0.0
    low = float(parts[0])
    high = float(parts[-1]) if len(parts) > 1 else low
    midpoint = (low + high) / 2.0
    if midpoint >= 55.0:
        return 1.0
    if midpoint >= 45.0:
        return 0.6
    if midpoint >= 35.0:
        return 0.3
    return 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class AccessibilityInclusionArchitect(BaseArchitect):
    """Evaluates disability/language/age/literacy inclusion across clusters."""

    @property
    def name(self) -> str:
        return "AccessibilityInclusionArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty means active for every product type — every consumer surface
        # (software, hardware, marketplaces, B2B) has inclusion expectations.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        literacy = _trait(traits, "digital_literacy")
        risk_av = _trait(traits, "risk_aversion")
        patience = _trait(traits, "patience_score")
        product_type = str(env_params.get("product_type", "saas")).lower()
        age_seniority = _age_seniority(cluster.demographic_profile)

        signals = {
            "disability": _has_any_keyword(assumptions, _DISABILITY_KEYWORDS),
            "language": _has_any_keyword(assumptions, _LANGUAGE_KEYWORDS),
            "age": _has_any_keyword(assumptions, _AGE_KEYWORDS),
            "literacy": _has_any_keyword(assumptions, _LITERACY_KEYWORDS),
        }
        evidence = _has_any_keyword(
            assumptions, _EVIDENCE_KEYWORDS, guard_negation=True
        )

        mentioned = sum(1 for detected in signals.values() if detected)
        gap = round(
            min(_GAP_CAP, _BASELINE_GAP + _GROUP_GAP_STEP * mentioned),
            4,
        )
        if evidence:
            gap = round(gap * _EVIDENCE_GAP_MULTIPLIER, 4)
        active = gap > _ACTIVE_THRESHOLD or (evidence and mentioned > 0)

        # ── Disability / assistive-technology barrier ───────────────────
        disability_factor = 1.0 if signals["disability"] or evidence else 0.55
        disability_barrier = _clamp(
            gap
            * disability_factor
            * (
                0.45 * (1.0 - literacy)
                + 0.30 * risk_av
                + 0.25 * age_seniority
            )
        )

        # ── Language / localization barrier ─────────────────────────────
        language_factor = 1.0 if signals["language"] else 0.55
        language_intensity = _LANGUAGE_INTENSITY.get(product_type, 0.7)
        language_barrier = _clamp(
            gap
            * language_factor
            * (
                0.45 * (1.0 - literacy)
                + 0.30 * age_seniority
                + 0.25 * language_intensity
            )
        )

        # ── Age / senior friction ───────────────────────────────────────
        age_factor = 1.0 if signals["age"] or age_seniority >= 0.5 else 0.5
        age_friction = _clamp(
            gap
            * age_factor
            * (0.55 * age_seniority + 0.45 * (1.0 - literacy))
        )

        # ── Credibility + funnel impact ─────────────────────────────────
        credibility = 1.0 if evidence else max(0.10, 1.0 - gap * 0.9)
        if not active:
            suppressor = 1.0
        else:
            raw_suppression = gap * (
                0.40 * (1.0 - literacy)
                + 0.30 * risk_av
                + 0.20 * age_seniority
                + 0.10 * (1.0 - patience)
            )
            if evidence:
                raw_suppression *= 0.45
            suppressor = 1.0 - min(_SUPPRESSOR_MAX_DROP, raw_suppression)
        suppressor = round(_clamp(suppressor, _SUPPRESSOR_MIN, 1.0), 4)

        lift = (
            round(min(_MAX_ADVANTAGE_LIFT, gap * 0.10), 4)
            if evidence and active and mentioned > 0
            else 0.0
        )

        flags: dict[str, bool] = {
            "accessibility_blocker": (
                disability_barrier >= 0.30 and not evidence
            ),
            "language_gap": language_barrier >= 0.25 and not evidence,
            "senior_friction": age_friction >= 0.35,
            "inclusive_advantage": evidence and mentioned > 0,
        }

        severity = (
            "CRITICAL"
            if flags["accessibility_blocker"]
            else "WARNING"
            if flags["language_gap"] or flags["senior_friction"]
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "accessibility_gap": gap,
                "disability_barrier": round(disability_barrier, 4),
                "language_barrier": round(language_barrier, 4),
                "age_friction": round(age_friction, 4),
                "accessibility_credibility": round(credibility, 4),
                "funnel_suppressor": suppressor,
                "inclusive_advantage_lift": lift,
                "inclusive_signal_strength": round(
                    min(1.0, mentioned / 4 + (0.25 if evidence else 0.0)),
                    4,
                ),
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Inclusion gap: {gap:.2f} | Disability: "
                    f"{disability_barrier:.2f} | Language: {language_barrier:.2f}"
                ),
                (
                    f"Credibility: {credibility:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f} | Evidence: {evidence}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        gap = float(output.metrics.get("accessibility_gap", 0.0))
        evidence = bool(output.flags.get("inclusive_advantage", False))
        if gap <= _ACTIVE_THRESHOLD and not evidence:
            return {}
        suppressor = float(output.metrics.get("funnel_suppressor", 1.0))
        lift = float(output.metrics.get("inclusive_advantage_lift", 0.0))
        overrides: dict[tuple[str, str], float] = {
            ("BROWSE", "CONSIDER"): _clamp(suppressor, 0.55, 0.999),
            ("CONSIDER", "DECIDE"): _clamp(suppressor + 0.06, 0.60, 0.999),
        }
        if lift > 0.0:
            overrides[("DECIDE", "PURCHASE")] = _clamp(
                1.0 + lift, 0.55, 1.15
            )
        return overrides

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [
            o
            for o in outputs
            if o.flags.get("accessibility_blocker")
        ]
        warning = [
            o
            for o in outputs
            if o.flags.get("language_gap") or o.flags.get("senior_friction")
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No accessibility or inclusion blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting inclusion evidence as the product scales"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters blocked by accessibility gaps; "
                f"{len(warning)} exposed to language/age friction"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.04 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Ship WCAG-aligned, language-inclusive, senior-friendly "
                "onboarding and publish accessibility evidence before scaling"
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["AccessibilityInclusionArchitect"]
