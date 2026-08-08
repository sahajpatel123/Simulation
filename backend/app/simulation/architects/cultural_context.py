"""
CulturalContextArchitect — Indian cultural-context evaluation.

Evaluates regional and cultural fit for a consumer cluster: language
accessibility, family vs. individual decision-making, festival/seasonal
timing alignment, local-brand trust, and religious/cultural sensitivity.
Produces per-cluster metrics, flags, narrative findings, and Markov
transition overrides. Pure compute — no I/O, no DB, no LLM.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition
from app.simulation.clusters.registry import ClusterRegistry

# Keyword groups detected from assumption text. These are the cultural
# signal vectors that the rest of the simulation engine cannot infer
# from cluster traits alone.
_FESTIVAL_KEYWORDS: tuple[str, ...] = (
    "diwali", "holi", "eid", "christmas", "pongal", "onam", "navratri",
    "wedding", "festive season", "festival", "seasonal", "monsoon",
    "raksha bandhan", "rakhi", "karva chauth", "ganesh",
)
_RELIGIOUS_KEYWORDS: tuple[str, ...] = (
    "vegetarian", "vegan", "halal", "jain", "hindu", "muslim", "sikh",
    "religious", "ritual", "auspicious", "karma", "dharma", "temple",
    "pilgrimage", "prayer", "custom", "tradition",
)
_LANGUAGE_KEYWORDS: tuple[str, ...] = (
    "hindi", "regional language", "vernacular", "tamil", "telugu",
    "bengali", "marathi", "multilingual", "local language", "bhasha",
    "indic", "kannada", "malayalam", "gujarati", "punjabi",
)


def _has_keyword(assumptions: list[dict], keywords: tuple[str, ...]) -> bool:
    """Return True if any assumption text contains any of the keywords."""
    for a in assumptions:
        text = str(a.get("text", a.get("assumption", ""))).lower()
        if any(k in text for k in keywords):
            return True
    return False


def _is_tier3(geo: str) -> bool:
    g = geo.lower()
    return g == "tier3" or g == "tier3_rural" or g.startswith("tier3_")


def _is_tier2(geo: str) -> bool:
    g = geo.lower()
    if _is_tier3(geo):
        return False
    return g == "tier2" or g.startswith("tier2_")


def _env_geo_tier(geo: str) -> str:
    """Normalise env geography to 'metro' | 'tier2' | 'tier3' | 'all'."""
    g = (geo or "").lower()
    if "tier3" in g or "rural" in g:
        return "tier3"
    if "tier2" in g:
        return "tier2"
    if "metro" in g or "tier1" in g:
        return "metro"
    return "all"


class CulturalContextArchitect(BaseArchitect):
    """
    Evaluates how well a product fits the cultural context of a cluster.
    Active for ALL product types — cultural fit is a universal concern.
    """

    @property
    def name(self) -> str:
        return "CulturalContextArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty list = applies to all product types (BaseArchitect
        # contract). Every conductor stack includes this architect, and
        # the cultural-fit read depends on its per-cluster metrics — a
        # narrower list would silently drop it from newer product types
        # (consumer_app, d2c, b2b_marketplace, productivity_tool,
        # smart_home) and turn the read into INSUFFICIENT_DATA while
        # still advertising product_type_supported=true.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t        = cluster.base_traits
        literacy = t["digital_literacy"]
        trust    = t["trust"]
        social   = t["social_orientation"]

        cluster.demographic_profile.get("age_bracket", "25-35")
        geo = cluster.demographic_profile.get("geography", "metro")
        tier3 = _is_tier3(geo)
        tier2 = _is_tier2(geo)

        # Product-target geography vs. cluster geography: if the cluster is
        # not in the product's target market, cultural fit is materially lower.
        env_geo = _env_geo_tier(str(env_params.get("geography", "")))
        cluster_geo_token = "tier3" if tier3 else "tier2" if tier2 else "metro"
        if env_geo == "all":
            geo_target_alignment = 0.78
        elif env_geo == cluster_geo_token:
            geo_target_alignment = 0.95
        else:
            geo_target_alignment = 0.35
        geo_target_alignment = round(max(0.05, min(0.99, geo_target_alignment)), 4)

        cid = cluster.cluster_id or ""
        family_oriented = any(
            x in cid for x in ("family", "couple", "parent", "joint", "household")
        )

        has_lang_support = _has_keyword(assumptions, _LANGUAGE_KEYWORDS)
        has_festival     = _has_keyword(assumptions, _FESTIVAL_KEYWORDS)
        has_religious    = _has_keyword(assumptions, _RELIGIOUS_KEYWORDS)

        # problem_urgency (from MarketTiming via DEPENDENCY_MAP) damps the
        # seasonal penalty: buyers with urgent problems buy regardless of
        # festival timing. agent_profile keys override base_traits when set.
        problem_urgency = float(agent_profile.get("problem_urgency_intensity", 0.5))

        # ── 1. Language accessibility ───────────────────────────────────
        if tier3 and literacy < 0.50:
            language_score = 0.30 + (0.15 if has_lang_support else 0.0)
        elif tier2 and literacy < 0.55:
            language_score = 0.55 + (0.15 if has_lang_support else 0.0)
        elif has_lang_support:
            language_score = 0.90
        else:
            language_score = 0.78
        language_score = round(max(0.05, min(0.99, language_score)), 4)

        # ── 2. Family influence factor ──────────────────────────────────
        family_influence = (
            0.45 * social
            + 0.35 * (1.0 if family_oriented else 0.0)
            + 0.20 * (0.6 if tier3 else 0.3 if tier2 else 0.1)
        )
        family_influence = round(max(0.05, min(0.99, family_influence)), 4)

        # ── 3. Local-brand trust ────────────────────────────────────────
        local_brand_trust = max(
            0.05, min(0.99,
                trust * (0.95 if tier3 else 0.85 if tier2 else 0.75)
                + (0.10 if has_lang_support else 0.0)
            ),
        )
        local_brand_trust = round(local_brand_trust, 4)

        # ── 4. Cultural alignment (composite) ───────────────────────────
        cultural_alignment = max(
            0.05, min(0.99,
                (0.45 * local_brand_trust
                 + 0.25 * language_score
                 + 0.20 * (1.0 - max(0.0, 0.6 - social))
                 + 0.10 * (0.8 if has_lang_support else 0.5))
                * (0.65 + 0.35 * geo_target_alignment)
            ),
        )
        cultural_alignment = round(cultural_alignment, 4)

        # ── 5. Seasonal / festival relevance ────────────────────────────
        if has_festival:
            seasonal_score = 0.82
        elif tier3:
            seasonal_score = 0.55
        else:
            seasonal_score = 0.65
        # Urgent problems dampen the seasonal penalty (range ±0.15).
        seasonal_modifier = 1.0 + 0.30 * (problem_urgency - 0.5)
        seasonal_score = round(
            max(0.05, min(0.99, seasonal_score * seasonal_modifier)), 4
        )

        # ── 6. Religious / cultural sensitivity risk ────────────────────
        if has_religious and literacy < 0.40:
            religious_risk = 0.78
        elif has_religious:
            religious_risk = 0.55
        else:
            religious_risk = 0.18 + (0.10 if tier3 else 0.0)
        religious_risk = round(max(0.05, min(0.99, religious_risk)), 4)

        # ── 7. Overall cultural correction multiplier ───────────────────
        overall = (
            max(0.30, language_score)
            * max(0.50, cultural_alignment)
            * max(0.60, 1.0 - 0.25 * religious_risk)
            * (1.10 if has_festival else 1.0)
            * (0.75 + 0.30 * geo_target_alignment)
        )
        overall = round(max(0.10, min(1.80, overall)), 4)

        metrics = {
            "cultural_alignment_score":     cultural_alignment,
            "language_accessibility_score": language_score,
            "family_influence_factor":      family_influence,
            "seasonal_relevance_score":     seasonal_score,
            "local_brand_trust":            local_brand_trust,
            "religious_sensitivity_risk":   religious_risk,
            "geo_target_alignment":         geo_target_alignment,
            "overall_cultural_correction":  overall,
        }

        flags = {
            "language_barrier_detected":     language_score < 0.55,
            "family_gatekeeper_risk":        family_influence > 0.72,
            "cultural_misalignment":         cultural_alignment < 0.50,
            "festival_timing_mismatch":      (not has_festival) and seasonal_score < 0.60,
            "religious_sensitivity_concern": religious_risk >= 0.55,
        }

        active_flags = [k for k, v in flags.items() if v]
        severity = (
            "CRITICAL" if len(active_flags) >= 3 else
            "WARNING"  if len(active_flags) >= 1 else
            "INFO"
        )

        narrative_findings = [
            (
                f"Language: {language_score:.2f}, "
                f"cultural alignment: {cultural_alignment:.2f}, "
                f"family influence: {family_influence:.2f}"
            ),
            (
                f"Seasonal relevance: {seasonal_score:.2f}, "
                f"religious sensitivity risk: {religious_risk:.2f}"
            ),
        ]

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics=metrics,
            flags=flags,
            narrative_findings=narrative_findings,
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        language  = float(output.metrics.get("language_accessibility_score", 0.7))
        alignment = float(output.metrics.get("cultural_alignment_score", 0.6))
        family    = float(output.metrics.get("family_influence_factor", 0.4))
        religious = float(output.metrics.get("religious_sensitivity_risk", 0.2))

        # (BROWSE, CONSIDER) and (CONSIDER, DECIDE) act as multipliers on
        # the base Markov transitions. (DECIDE, PURCHASE) is a replacement
        # value clamped to [0.01, 0.95] by the conductor.
        return {
            ("BROWSE",   "CONSIDER"): round(max(0.40, min(1.30,
                0.75 + 0.30 * language + 0.20 * alignment)), 4),
            ("CONSIDER", "DECIDE"):   round(max(0.40, min(1.30,
                0.85 + 0.20 * alignment - 0.20 * family)), 4),
            ("DECIDE",   "PURCHASE"): round(max(0.05, min(0.95,
                0.62 + 0.28 * alignment - 0.50 * religious)), 4),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        if not outputs:
            return DomainReport(
                architect_name=self.name,
                primary_finding="No cultural context outputs to aggregate",
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action="Re-run simulation with at least one cluster",
                severity="INFO",
            )

        registry = ClusterRegistry()
        total_weight = (
            sum(c.population_weight for c in registry.all_clusters()) or 1.0
        )

        lang_gap    = [o for o in outputs if o.flags.get("language_barrier_detected")]
        family_gate = [o for o in outputs if o.flags.get("family_gatekeeper_risk")]
        religious   = [o for o in outputs if o.flags.get("religious_sensitivity_concern")]
        misaligned  = [o for o in outputs if o.flags.get("cultural_misalignment")]
        seasonal    = [o for o in outputs if o.flags.get("festival_timing_mismatch")]

        affected = list({
            o.cluster_id
            for o in lang_gap + family_gate + religious + misaligned + seasonal
        })

        affected_weight = 0.0
        for cid in affected:
            c = registry.get_cluster(cid)
            if c:
                affected_weight += c.population_weight
        population_fraction = round(affected_weight / total_weight, 4)

        primary = (
            f"{len(lang_gap)} clusters face language barrier; "
            f"{len(family_gate)} have family gatekeeper risk; "
            f"{len(religious)} have religious sensitivity concerns; "
            f"{len(seasonal)} have festival-timing mismatch"
        )

        # Branch the recommendation on the dominant issue bucket so the
        # DomainReport surfaces a concrete next action instead of a generic
        # summary. Stable tiebreak order: language > family > religious >
        # seasonal (sorted by count desc; equal counts preserve listed order).
        issue_buckets: list[tuple[int, str, str]] = [
            (len(lang_gap), "language",
             "Add Hindi and regional language UI; consider voice-first "
             "onboarding for tier-2/3 clusters with low literacy"),
            (len(family_gate), "family",
             "Design for family/collective purchase decisions; expect longer "
             "decision cycles and consider household-sharing features"),
            (len(religious), "religious",
             "Validate product against vegetarian, halal, and Jain "
             "requirements; review imagery and copy for cultural/religious "
             "sensitivity"),
            (len(seasonal), "seasonal",
             "Align launch with Diwali, wedding, or harvest seasons; run "
             "festival-themed seasonal campaigns"),
        ]
        issue_buckets.sort(key=lambda b: b[0], reverse=True)
        if issue_buckets[0][0] > 0:
            recommended_action = issue_buckets[0][2]
        else:
            recommended_action = (
                "No dominant cultural blockers detected; maintain current "
                "cultural-fit strategy"
            )

        return DomainReport(
            architect_name=self.name,
            primary_finding=primary,
            affected_cluster_ids=affected,
            population_fraction=population_fraction,
            conversion_impact=round(
                len(lang_gap) * 0.04
                + len(family_gate) * 0.03
                + len(religious) * 0.05
                + len(seasonal) * 0.02,
                4,
            ),
            recommended_action=recommended_action,
            severity="WARNING" if (lang_gap or family_gate or religious) else "INFO",
        )
