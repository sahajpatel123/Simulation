from __future__ import annotations
from dataclasses import dataclass
from typing import Any

MAX_MUTATION_PER_TRAIT = 0.35
TRAIT_FLOOR            = 0.05


def _architect_metrics_blob(arch_out: Any) -> dict[str, Any]:
    """Support dict payloads (tests) and ArchitectOutput-like objects (Conductor)."""
    if arch_out is None:
        return {}
    if isinstance(arch_out, dict):
        m = arch_out.get("metrics")
        return m if isinstance(m, dict) else {}
    m = getattr(arch_out, "metrics", None)
    return m if isinstance(m, dict) else {}


@dataclass
class CognitiveStateMutation:
    trigger_name:  str
    trait_affected:str
    delta:         float        # negative = degradation
    reason:        str
    cluster_id:    str

@dataclass
class CognitiveStateResult:
    cluster_id:         str
    mutations_applied:  list[CognitiveStateMutation]
    mutated_profile:    dict[str, float]  # updated agent_profile traits
    total_trust_delta:  float
    total_frustration:  float             # accumulated patience loss
    total_intent_drop:  float             # accumulated motivation loss
    any_mutation_fired: bool

class CognitiveStateMutator:
    """
    Phase 1 — three mutation triggers only.
    Mutations modify agent_profile traits before
    the transition matrix is built by the Conductor.
    Downstream architects receive the mutated profile.

    Rules:
      Max total mutation per trait: -0.35
      Minimum trait value after mutation: 0.05
      All mutations are logged in CognitiveStateResult.
      Mutations stack across triggers.
      Positive mutations not implemented in Phase 1.
    """

    def apply(
        self,
        cluster_id:        str,
        agent_profile:     dict[str, Any],
        architect_outputs: dict[str, Any],
        assumptions:       list[dict[str, Any]],
    ) -> CognitiveStateResult:

        # Work on a mutable copy — never modify original
        profile   = {k: float(v) for k, v in agent_profile.items()
                     if isinstance(v, (int, float))}
        mutations: list[CognitiveStateMutation] = []

        # ── Extract architect metrics ──
        trust_m    = _architect_metrics_blob(architect_outputs.get("TrustArchitect"))
        pricing_m  = _architect_metrics_blob(architect_outputs.get("PricingArchitect"))
        onboard_m  = _architect_metrics_blob(architect_outputs.get("OnboardingArchitect"))
        timing_m   = _architect_metrics_blob(architect_outputs.get("MarketTimingArchitect"))

        # ── MUTATION 1: trust_delta ──
        # Trigger: unknown brand (bdm < 0.50) AND no free trial in assumptions
        bdm        = float(trust_m.get("brand_deficit_multiplier", 1.0))
        free_trial = float(trust_m.get("free_trial_as_trust_substitute", 0.0))
        has_trial  = any(
            any(w in str(a.get("text", a.get("assumption", ""))).lower()
                for w in ["free trial","free plan","freemium","money back","money-back","refund"])
            for a in assumptions
        )

        if bdm < 0.50 and not has_trial and free_trial < 0.30:
            delta = -0.15
            mutations.append(CognitiveStateMutation(
                trigger_name="trust_delta",
                trait_affected="trust",
                delta=delta,
                reason=f"Unknown brand (bdm={bdm:.2f}) with no free trial — trust actively erodes",
                cluster_id=cluster_id,
            ))
            profile["trust"] = max(
                TRAIT_FLOOR,
                profile.get("trust", 0.5) + delta,
            )

        # ── MUTATION 2: frustration ──
        # Trigger: will_pay < 0.20 AND onboarding steps > limit < 4
        will_pay   = float(pricing_m.get("will_pay_probability", 0.5))
        disclosure = float(onboard_m.get("progressive_disclosure_limit", 6.0))

        if will_pay < 0.20 and disclosure < 4.0:
            delta = -0.20
            mutations.append(CognitiveStateMutation(
                trigger_name="frustration",
                trait_affected="patience_score",
                delta=delta,
                reason=f"Can't afford (will_pay={will_pay:.2f}) AND too many steps (limit={disclosure:.0f}) — frustration, not just abandonment",
                cluster_id=cluster_id,
            ))
            profile["patience_score"] = max(
                TRAIT_FLOOR,
                profile.get("patience_score", 0.5) + delta,
            )

        # ── MUTATION 3: intent_clarity ──
        # Trigger: category_awareness < 0.35
        # Founder solving a problem the cluster doesn't know they have
        awareness = float(timing_m.get("category_awareness_score", 0.6))

        if awareness < 0.35:
            delta = -0.12
            mutations.append(CognitiveStateMutation(
                trigger_name="intent_clarity",
                trait_affected="motivation",
                delta=delta,
                reason=f"Category awareness {awareness:.2f} — cluster doesn't know they have this problem, intent collapses before evaluation",
                cluster_id=cluster_id,
            ))
            profile["motivation"] = max(
                TRAIT_FLOOR,
                profile.get("motivation", 0.5) + delta,
            )

        # ── MUTATION 4: positive_trust_boost ──
        # Trigger: known brand (bdm >= 0.75) AND free trial available
        if bdm >= 0.75 and has_trial:
            delta = +0.10
            mutations.append(CognitiveStateMutation(
                trigger_name="positive_trust_boost",
                trait_affected="trust",
                delta=delta,
                reason=f"Known brand (bdm={bdm:.2f}) with free trial — trust actively builds",
                cluster_id=cluster_id,
            ))
            profile["trust"] = min(1.0, profile.get("trust", 0.5) + delta)

        # ── MUTATION 5: positive_value_confidence ──
        # Trigger: will_pay >= 0.60 AND progressive_disclosure >= 5
        if will_pay >= 0.60 and disclosure >= 5.0:
            delta = +0.15
            mutations.append(CognitiveStateMutation(
                trigger_name="positive_value_confidence",
                trait_affected="patience_score",
                delta=delta,
                reason=f"Clear value (will_pay={will_pay:.2f}) with manageable steps (limit={disclosure:.0f}) — patience holds",
                cluster_id=cluster_id,
            ))
            profile["patience_score"] = min(1.0, profile.get("patience_score", 0.5) + delta)

        # ── MUTATION 6: positive_awareness_boost ──
        # Trigger: category_awareness >= 0.70
        if awareness >= 0.70:
            delta = +0.08
            mutations.append(CognitiveStateMutation(
                trigger_name="positive_awareness_boost",
                trait_affected="motivation",
                delta=delta,
                reason=f"High category awareness {awareness:.2f} — cluster knows the problem, motivation sustained",
                cluster_id=cluster_id,
            ))
            profile["motivation"] = min(1.0, profile.get("motivation", 0.5) + delta)

        # ── Enforce per-trait mutation cap (both directions) ──
        original = {k: float(v) for k, v in agent_profile.items()
                    if isinstance(v, (int, float))}
        for trait in ["trust", "patience_score", "motivation"]:
            orig  = original.get(trait, 0.5)
            curr  = profile.get(trait, orig)
            total_delta = curr - orig
            if total_delta < -MAX_MUTATION_PER_TRAIT:
                profile[trait] = max(TRAIT_FLOOR, orig - MAX_MUTATION_PER_TRAIT)
            if total_delta > MAX_MUTATION_PER_TRAIT:
                profile[trait] = min(1.0, orig + MAX_MUTATION_PER_TRAIT)

        # ── Aggregate totals for logging ──
        total_trust       = profile.get("trust", 0.5)       - original.get("trust", 0.5)
        total_frustration = profile.get("patience_score", 0.5) - original.get("patience_score", 0.5)
        total_intent      = profile.get("motivation", 0.5)  - original.get("motivation", 0.5)

        return CognitiveStateResult(
            cluster_id=cluster_id,
            mutations_applied=mutations,
            mutated_profile=profile,
            total_trust_delta=round(total_trust, 4),
            total_frustration=round(total_frustration, 4),
            total_intent_drop=round(total_intent, 4),
            any_mutation_fired=len(mutations) > 0,
        )
