"""
Pure buyer-persona brief builder for completed simulation results.

Answers the founder's "who exactly should I be selling to, and how do I
talk to them?" question. The cluster-opportunity matrix ranks clusters by
addressable conversion gap, but only carries name + population weight.
This module turns that ranking into persona cards by joining each ranked
cluster with its full registry profile:

* **Profile** — description, 8 canonical traits, dominant behavior
  pattern, product affinities, demographic tags.
* **Messaging angle** — a deterministic, trait-driven hook for how to
  position the product to that persona (price-first, proof-first,
  risk-reversal, simplicity, aspiration, social proof, speed, outcomes).
* **Risk watch** — the persona's known failure modes, so founders can
  pre-empt the reasons this segment drops out.
* **Recommended focus** — segment-aware action language mirroring the
  opportunity matrix (QUICK_WIN / TRANSFORM / NICHE / DEPRIORITIZE).

The builder reuses ``build_cluster_opportunity_matrix`` so the segment
classification, opportunity scores, and focus recommendations can never
drift from the existing GTM analytics. No DB / I/O / LLM — verifiable
with plain dicts.
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.buyer_personas import BuyerPersona, BuyerPersonasOut
from app.simulation.cluster_opportunity import (
    DEFAULT_BENCHMARK,
    build_cluster_opportunity_matrix,
)

# Canonical trait order — matches cluster_parameters column conventions.
TRAIT_ORDER: tuple[str, ...] = (
    "income_level",
    "digital_literacy",
    "motivation",
    "trust",
    "price_sensitivity",
    "risk_aversion",
    "patience_score",
    "social_orientation",
)

# Thresholds for deterministic messaging-angle selection.
PRICE_SENSITIVE_MIN: float = 0.70
LOW_TRUST_MAX: float = 0.45
HIGH_RISK_AVERSION_MIN: float = 0.60
LOW_DIGITAL_LITERACY_MAX: float = 0.45
HIGH_MOTIVATION_MIN: float = 0.80
HIGH_SOCIAL_ORIENTATION_MIN: float = 0.65
LOW_PATIENCE_MAX: float = 0.45

# Cap persona card lists so the payload stays scannable.
MAX_AFFINITIES: int = 3
MAX_RISK_ITEMS: int = 2


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _overall_conversion(results: dict[str, Any]) -> float:
    return max(
        0.0,
        min(
            1.0,
            _safe_float(
                results.get(
                    "population_weighted_conversion",
                    results.get("conversion_rate"),
                )
            ),
        ),
    )


def _traits(raw: Any) -> dict[str, float]:
    """Extract the 8 canonical traits in stable order, skipping garbage."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: round(_safe_float(raw.get(key)), 4)
        for key in TRAIT_ORDER
        if key in raw
    }


def _string_list(raw: Any, limit: int | None = None) -> list[str]:
    if not isinstance(raw, list):
        return []
    items = [str(item) for item in raw if item is not None and str(item).strip()]
    if limit is not None:
        items = items[:limit]
    return items


def _string_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if value is not None
    }


def _messaging_angle(traits: dict[str, float]) -> str:
    """Deterministic positioning hook derived from the persona's traits."""
    price = traits.get("price_sensitivity")
    trust = traits.get("trust")
    risk = traits.get("risk_aversion")
    literacy = traits.get("digital_literacy")
    motivation = traits.get("motivation")
    social = traits.get("social_orientation")
    patience = traits.get("patience_score")

    if price is not None and price >= PRICE_SENSITIVE_MIN:
        return (
            "Lead with price transparency, a free tier or trial, and "
            "clear ROI math."
        )
    if trust is not None and trust < LOW_TRUST_MAX:
        return (
            "Lead with third-party proof: reviews, certifications, and "
            "named customers."
        )
    if risk is not None and risk >= HIGH_RISK_AVERSION_MIN:
        return (
            "De-risk the decision: money-back guarantee, pilot programme, "
            "or a no-strings refund policy."
        )
    if literacy is not None and literacy < LOW_DIGITAL_LITERACY_MAX:
        return (
            "Simplify onboarding and offer human-assisted setup before "
            "expecting self-serve adoption."
        )
    if motivation is not None and motivation >= HIGH_MOTIVATION_MIN:
        return (
            "Lead with aspirational outcomes and early-adopter status "
            "rather than feature lists."
        )
    if social is not None and social >= HIGH_SOCIAL_ORIENTATION_MIN:
        return (
            "Use social proof, community signals, and referral or "
            "influencer framing."
        )
    if patience is not None and patience < LOW_PATIENCE_MAX:
        return (
            "Compress time-to-value: show a quick win in the first session "
            "and avoid multi-step onboarding."
        )
    return (
        "Lead with specific, quantified outcomes and performance proof "
        "tied to the customer's job."
    )


def _recommended_focus(segment: str, cluster_name: str) -> str:
    name = cluster_name or "this segment"
    if segment == "QUICK_WIN":
        return (
            f"Prioritise near-term fixes for {name} — high reach with a "
            "moderate conversion gap."
        )
    if segment == "TRANSFORM":
        return (
            f"Design a strategic bet for {name} — a large conversion gap "
            "on a high-weight segment."
        )
    if segment == "NICHE":
        return (
            f"Protect {name} — it already converts well; mine its "
            "messaging for broader segments."
        )
    return (
        f"Revisit {name} later — low population weight and weak "
        "conversion keep it off the critical path."
    )


def _build_persona(
    opportunity: Any,
    profile: dict[str, Any],
) -> BuyerPersona:
    """Render one ranked cluster as a persona card."""
    traits = _traits(profile.get("base_traits"))
    failure_modes = _string_list(profile.get("known_failure_modes"))
    return BuyerPersona(
        cluster_id=opportunity.cluster_id,
        cluster_name=str(profile.get("name") or opportunity.cluster_name or ""),
        description=str(profile.get("description") or ""),
        population_weight=round(_safe_float(opportunity.population_weight), 6),
        conversion_rate=round(_safe_float(opportunity.conversion_rate), 4),
        conversion_gap=round(_safe_float(opportunity.conversion_gap), 4),
        opportunity_score=round(_safe_float(opportunity.opportunity_score), 6),
        segment=str(opportunity.segment or "DEPRIORITIZE"),
        estimated_lift=round(_safe_float(opportunity.estimated_lift), 6),
        traits=traits,
        dominant_behavior_pattern=str(
            profile.get("dominant_behavior_pattern") or ""
        ),
        messaging_angle=_messaging_angle(traits),
        product_affinities=_string_list(
            profile.get("product_affinities"), MAX_AFFINITIES
        ),
        demographic_profile=_string_map(profile.get("demographic_profile")),
        known_failure_modes=failure_modes,
        risk_watch=failure_modes[:MAX_RISK_ITEMS],
        recommended_focus=_recommended_focus(
            str(opportunity.segment or "DEPRIORITIZE"),
            str(profile.get("name") or opportunity.cluster_name or ""),
        ),
    )


def build_buyer_personas(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    cluster_summaries: list[dict[str, Any]] | None = None,
    cluster_registry: dict[str, dict[str, Any]] | None = None,
    benchmark: float = DEFAULT_BENCHMARK,
    limit: int = 10,
) -> BuyerPersonasOut:
    """
    Build ranked buyer-persona briefs from persisted results + registry
    profiles. Safe on empty / malformed payloads — returns a zero-state
    payload rather than raising.
    """
    data = _coerce_results(results)
    effective_limit = max(1, min(int(limit) if isinstance(limit, int) else 10, 52))

    matrix = build_cluster_opportunity_matrix(
        data,
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        signal_quality=signal_quality,
        cluster_summaries=cluster_summaries,
        cluster_registry=cluster_registry,
        benchmark=benchmark,
        limit=52,
    )

    registry = cluster_registry or {}
    personas: list[BuyerPersona] = []
    for opportunity in matrix.opportunities:
        profile = registry.get(opportunity.cluster_id)
        if not isinstance(profile, dict) or not profile.get("name"):
            # A ranked cluster without a registry profile is not a persona
            # card — skip rather than emit an empty stub.
            continue
        personas.append(_build_persona(opportunity, profile))
        if len(personas) >= effective_limit:
            break

    return BuyerPersonasOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        signal_quality=(
            float(signal_quality) if signal_quality is not None else None
        ),
        overall_conversion=_overall_conversion(data),
        total_agents=_safe_int(data.get("total_agents")),
        persona_count=len(personas),
        primary_target_persona=personas[0].cluster_id if personas else None,
        personas=personas,
        focus_recommendations=list(matrix.focus_recommendations),
        meta={
            "cluster_summaries_used": bool(cluster_summaries),
            "benchmark": matrix.meta.get("benchmark", benchmark),
            "ranked_from_opportunity_matrix": True,
        },
    )


__all__ = ["build_buyer_personas"]
