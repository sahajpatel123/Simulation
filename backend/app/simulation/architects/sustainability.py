"""
SustainabilityArchitect — environmental & social (ESG) positioning evaluation.

Evaluates how a startup's environmental and social claims shape consumer
demand across the 52 clusters. The rest of the engine models price, trust,
retention and virality, but has no signal for sustainability positioning —
founders routinely claim "eco-friendly", "recycled" or "fair-trade" inputs,
and a meaningful share of consumers (and enterprise procurement teams) let
that change what they buy and how much they pay.

What this architect does:

* **Claim detection** — scans assumption text for environmental keywords
  (recycled, biodegradable, carbon-neutral, plastic-free, ...) and social
  keywords (fair trade, ethical sourcing, b-corp, ...).
* **Credibility** — third-party evidence markers (certified, audited,
  verified, LCA, ...) raise ``claim_credibility``; claims without evidence
  surface a ``greenwashing_risk`` flag.
* **Affinity** — ``esg_affinity`` weights the cluster traits that actually
  predict ESG buying behaviour (social orientation, motivation, digital
  literacy, trust, income).
* **Green premium tolerance** — price-sensitive, low-income clusters cannot
  absorb an ESG premium; that becomes ``premium_friction``.
* **Conversion effect** — a deterministic ``conversion_lift`` per cluster,
  scaled by an optional ``env_params["sustainability_weight"]`` (default 1.0,
  clamped 0..2) so founders can tune how strongly claims move demand.
* **Markov overrides** — positioned clusters get a small CONSIDER→DECIDE /
  DECIDE→PURCHASE boost proportional to affinity minus friction.

Pure compute — no I/O, no DB, no LLM. The route layer (Conductor) supplies
clusters, agent profiles, assumptions and env params.
"""
from __future__ import annotations

import math
import re
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition
from app.simulation.clusters.registry import ClusterRegistry

# ── Keyword groups ────────────────────────────────────────────────────
# Word-boundary matching (not substring) avoids false positives like
# "greenhouse" (matches "green") or "community manager" (matches "community").
# Hyphenated compounds carry both hyphenated and space-separated variants so
# "plastic-free" and "plastic free" are detected identically.

_ENV_KEYWORDS: tuple[str, ...] = (
    "eco", "eco-friendly", "environmentally friendly", "sustainable",
    "sustainability", "recycled", "recyclable", "biodegradable",
    "compostable", "carbon-neutral", "carbon neutral", "carbon footprint",
    "zero-waste", "zero waste", "plastic-free", "plastic free", "renewable",
    "green", "emission", "energy-efficient", "energy efficient", "upcycled",
    "plant-based", "plant based", "cruelty-free", "cruelty free",
    "low-impact", "low impact", "climate",
)

_SOCIAL_KEYWORDS: tuple[str, ...] = (
    "fair trade", "fair-trade", "ethical", "ethically sourced",
    "ethically-sourced", "fair wages", "fair wage", "worker-owned",
    "worker owned", "community",
    "b-corp", "b corp", "charity", "donation", "giveback",
    "local sourcing", "artisan", "handmade", "women-owned",
    "women owned", "minority-owned", "minority owned", "inclusive",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "certified", "certification", "verified", "verification",
    "third-party", "third party", "audited", "lifecycle", "lca",
    "plastic neutral", "transparent", "impact report", "traceable",
    "sourcing policy", "esg report", "lab tested", "compliant",
)

# Trait blend that predicts ESG buying behaviour. Social orientation
# dominates (peer-visible values), then motivation and awareness.
_AFFINITY_WEIGHTS: dict[str, float] = {
    "social_orientation": 0.45,
    "motivation": 0.20,
    "digital_literacy": 0.15,
    "trust": 0.10,
    "income_level": 0.10,
}

_MAX_CONVERSION_LIFT: float = 0.30
_CREDIBILITY_WITH_EVIDENCE: float = 1.0
_CREDIBILITY_WITHOUT_EVIDENCE: float = 0.25


def _has_keyword(assumptions: list[dict[str, Any]], keywords: tuple[str, ...]) -> bool:
    """True when any assumption text mentions any keyword (word-boundary)."""
    if not assumptions:
        return False
    for assumption in assumptions:
        if isinstance(assumption, dict):
            text = str(assumption.get("text", assumption.get("assumption", ""))).lower()
        else:
            text = str(assumption).lower()
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                return True
    return False


def _trait(traits: dict[str, float], key: str, default: float = 0.5) -> float:
    value = traits.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _safe_weight(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(2.0, parsed))


def _safe_metric(value: Any, default: float) -> float:
    """Parse a metric value, falling back to ``default`` on garbage input."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


class SustainabilityArchitect(BaseArchitect):
    """Evaluates ESG positioning across the consumer population."""

    @property
    def name(self) -> str:
        return "SustainabilityArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty means active for every product type — sustainability claims
        # are relevant to consumer apps, hardware, marketplaces and B2B alike.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        income = _trait(traits, "income_level")
        _trait(traits, "digital_literacy")
        _trait(traits, "motivation")
        _trait(traits, "trust")
        price_sens = _trait(traits, "price_sensitivity")
        _trait(traits, "social_orientation")

        env_claim = _has_keyword(assumptions, _ENV_KEYWORDS)
        social_claim = _has_keyword(assumptions, _SOCIAL_KEYWORDS)
        evidence = _has_keyword(assumptions, _EVIDENCE_KEYWORDS)
        has_claims = env_claim or social_claim

        breadth = (0.6 if env_claim else 0.0) + (0.4 if social_claim else 0.0)
        credibility = (
            _CREDIBILITY_WITH_EVIDENCE if evidence else _CREDIBILITY_WITHOUT_EVIDENCE
        )
        signal = (
            round(min(1.0, breadth * (0.40 + 0.60 * credibility)), 4)
            if has_claims else 0.0
        )

        esg_affinity = round(
            max(0.0, min(1.0, sum(
                _AFFINITY_WEIGHTS[k] * _trait(traits, k)
                for k in _AFFINITY_WEIGHTS
            ))),
            4,
        )
        green_premium_tolerance = round(
            max(0.0, min(1.0, (1.0 - price_sens) * (0.55 + 0.45 * income))),
            4,
        )

        weight = _safe_weight(env_params.get("sustainability_weight"))
        conversion_lift = (
            round(
                max(0.0, min(_MAX_CONVERSION_LIFT,
                    signal * esg_affinity
                    * (0.35 + 0.65 * green_premium_tolerance)
                    * _MAX_CONVERSION_LIFT * weight
                )),
                4,
            )
            if has_claims else 0.0
        )
        premium_friction = (
            round(
                max(0.0, min(1.0,
                    price_sens * (1.0 - income) * (0.50 + 0.50 * signal)
                )),
                4,
            )
            if has_claims else 0.0
        )

        flags: dict[str, bool] = {
            "sustainability_positioned": has_claims,
            "greenwashing_risk": (
                has_claims and not evidence and breadth >= 0.6
            ),
            "premium_friction": premium_friction >= 0.55,
            "strong_esg_affinity": esg_affinity >= 0.65,
            "low_esg_reach": has_claims and esg_affinity < 0.40,
        }
        [k for k, v in flags.items() if v]
        severity = (
            "CRITICAL"
            if flags["greenwashing_risk"] and flags["premium_friction"]
            else "WARNING"
            if flags["greenwashing_risk"]
            or flags["premium_friction"]
            or flags["low_esg_reach"]
            else "INFO"
        )

        narrative_findings = [
            (
                f"ESG affinity: {esg_affinity:.2f}, green premium tolerance: "
                f"{green_premium_tolerance:.2f}"
            ),
            (
                f"Sustainability signal: {signal:.2f} "
                f"(evidence-backed: {evidence}), conversion lift: {conversion_lift:.3f}"
            ),
        ]

        metrics: dict[str, float] = {
            "sustainability_signal": signal,
            "esg_affinity": esg_affinity,
            "green_premium_tolerance": green_premium_tolerance,
            "conversion_lift": conversion_lift,
            "premium_friction": premium_friction,
            "claim_credibility": credibility,
        }

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
        if _safe_metric(output.metrics.get("sustainability_signal"), 0.0) <= 0.0:
            return {}

        affinity = _safe_metric(output.metrics.get("esg_affinity"), 0.5)
        friction = _safe_metric(output.metrics.get("premium_friction"), 0.0)
        return {
            ("CONSIDER", "DECIDE"): round(
                max(0.40, min(1.30, 0.92 + 0.28 * affinity - 0.18 * friction)),
                4,
            ),
            ("DECIDE", "PURCHASE"): round(
                max(0.05, min(0.95, 0.62 + 0.30 * affinity - 0.35 * friction)),
                4,
            ),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        if not outputs:
            return DomainReport(
                architect_name=self.name,
                primary_finding="No sustainability outputs to aggregate",
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

        positioned = [o for o in outputs if _safe_metric(o.metrics.get("sustainability_signal"), 0.0) > 0.0]
        greenwash = [o for o in outputs if o.flags.get("greenwashing_risk")]
        friction = [o for o in outputs if o.flags.get("premium_friction")]
        low_reach = [o for o in outputs if o.flags.get("low_esg_reach")]
        strong = [o for o in outputs if o.flags.get("strong_esg_affinity")]

        affected = list({
            o.cluster_id
            for o in greenwash + friction + low_reach + strong
        })
        affected_weight = 0.0
        for cid in affected:
            cluster = registry.get_cluster(cid)
            if cluster:
                affected_weight += cluster.population_weight
        population_fraction = round(affected_weight / total_weight, 4)

        if not positioned:
            return DomainReport(
                architect_name=self.name,
                primary_finding="No sustainability claims detected in assumptions — ESG positioning is not influencing demand",
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Consider adding evidence-backed sustainability claims "
                    "(certified materials, fair-trade sourcing) if the audience cares"
                ),
                severity="INFO",
            )

        weighted_lift = 0.0
        weighted_affinity = 0.0
        positioned_weight = 0.0
        for output in positioned:
            cluster = registry.get_cluster(output.cluster_id)
            weight = cluster.population_weight if cluster else 0.0
            positioned_weight += weight
            weighted_lift += weight * _safe_metric(output.metrics.get("conversion_lift"), 0.0)
            weighted_affinity += weight * _safe_metric(output.metrics.get("esg_affinity"), 0.0)
        positioned_weight = positioned_weight or 1.0
        conversion_impact = round(weighted_lift / positioned_weight, 4)
        avg_affinity = round(weighted_affinity / positioned_weight, 4)

        primary = (
            f"{len(positioned)} clusters respond to sustainability positioning "
            f"(weighted affinity {avg_affinity:.2f}, weighted conversion lift "
            f"{conversion_impact:.3f}); {len(greenwash)} clusters flag "
            f"greenwashing risk; {len(friction)} face premium friction"
        )

        issue_buckets: list[tuple[int, str, str]] = [
            (
                len(greenwash), "greenwashing",
                "Back sustainability claims with third-party certifications "
                "(certified organic, plastic-neutral, audited sourcing) before "
                "charging a green premium",
            ),
            (
                len(friction), "premium",
                "Price-sensitive clusters cannot absorb the ESG premium — add a "
                "value tier or absorb the sustainability cost into the base price",
            ),
            (
                len(low_reach), "reach",
                "Sustainability affinity is weak in target clusters — pair claims "
                "with education and visible impact metrics instead of premium pricing",
            ),
        ]
        issue_buckets.sort(key=lambda bucket: bucket[0], reverse=True)
        if issue_buckets[0][0] > 0:
            recommended_action = issue_buckets[0][2]
        else:
            recommended_action = (
                "ESG positioning is credible and well-matched to cluster "
                "affinity — keep claims evidence-backed and track impact metrics"
            )

        return DomainReport(
            architect_name=self.name,
            primary_finding=primary,
            affected_cluster_ids=affected,
            population_fraction=population_fraction,
            conversion_impact=conversion_impact,
            recommended_action=recommended_action,
            severity=(
                "CRITICAL"
                if greenwash and friction
                else "WARNING"
                if greenwash or friction or low_reach
                else "INFO"
            ),
        )
