"""
Tests for ``app.simulation.cognitive_state`` — pure-Python mutator.

Locks down the six mutation triggers (3 negative, 3 positive), the
per-trait cap (-0.35 floor / +0.35 ceiling relative to original), the
trait floor (0.05) for negative mutations and ceiling (1.0) for
positive, the aggregation of total_trust_delta / total_frustration /
total_intent_drop, and the ``any_mutation_fired`` flag.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_profile(
    trust: float = 0.5,
    patience: float = 0.5,
    motivation: float = 0.5,
) -> dict[str, float]:
    return {
        "trust": trust,
        "patience_score": patience,
        "motivation": motivation,
    }


def _arch(
    *,
    bdm: float = 1.0,
    free_trial_substitute: float = 0.0,
    will_pay: float = 0.5,
    disclosure: float = 6.0,
    awareness: float = 0.6,
) -> dict[str, dict[str, Any]]:
    """Architect outputs in dict form (conductor shape)."""
    return {
        "TrustArchitect": {
            "metrics": {
                "brand_deficit_multiplier": bdm,
                "free_trial_as_trust_substitute": free_trial_substitute,
            }
        },
        "PricingArchitect": {"metrics": {"will_pay_probability": will_pay}},
        "OnboardingArchitect": {
            "metrics": {"progressive_disclosure_limit": disclosure}
        },
        "MarketTimingArchitect": {
            "metrics": {"category_awareness_score": awareness}
        },
    }


def _assumption(text: str) -> dict[str, str]:
    return {"text": text}


# ---------------------------------------------------------------------------
# Negative trigger 1: trust_delta
# ---------------------------------------------------------------------------


def test_trust_delta_fires_when_bdm_low_and_no_trial() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5)
    out = m.apply(
        cluster_id="metro_power_professional",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.30, free_trial_substitute=0.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "trust_delta" in names
    # trust was reduced.
    assert out.mutated_profile["trust"] < profile["trust"]


def test_trust_delta_skipped_when_bdm_high() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(bdm=0.90),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "trust_delta" not in names


def test_trust_delta_skipped_when_assumption_mentions_free_trial() -> None:
    """Any keyword ('free trial', 'freemium', etc.) suppresses the trigger."""
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(bdm=0.30),
        assumptions=[_assumption("Users get a 14-day free trial.")],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "trust_delta" not in names


def test_trust_delta_skipped_when_free_trial_substitute_high() -> None:
    """If the architect's free_trial_as_trust_substitute >= 0.30, skip."""
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(bdm=0.30, free_trial_substitute=0.5),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "trust_delta" not in names


def test_trust_delta_floor_at_005() -> None:
    """Repeated trust_delta cannot push trust below 0.05."""
    from app.simulation.cognitive_state import (
        MAX_MUTATION_PER_TRAIT,
        TRAIT_FLOOR,
        CognitiveStateMutator,
    )

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.10)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.10, free_trial_substitute=0.0),
        assumptions=[],
    )
    assert out.mutated_profile["trust"] >= TRAIT_FLOOR
    # And the negative cap enforces MAX_MUTATION_PER_TRAIT.
    assert (
        profile["trust"] - out.mutated_profile["trust"]
    ) <= MAX_MUTATION_PER_TRAIT + 1e-9


# ---------------------------------------------------------------------------
# Negative trigger 2: frustration
# ---------------------------------------------------------------------------


def test_frustration_fires_when_cant_afford_and_disclosure_low() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(patience=0.6),
        architect_outputs=_arch(will_pay=0.10, disclosure=2.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "frustration" in names
    assert out.mutated_profile["patience_score"] < 0.6


def test_frustration_skipped_when_will_pay_high() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(will_pay=0.50, disclosure=2.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "frustration" not in names


def test_frustration_skipped_when_disclosure_high() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(will_pay=0.10, disclosure=5.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "frustration" not in names


# ---------------------------------------------------------------------------
# Negative trigger 3: intent_clarity
# ---------------------------------------------------------------------------


def test_intent_clarity_fires_when_awareness_low() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(motivation=0.5),
        architect_outputs=_arch(awareness=0.20),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "intent_clarity" in names
    assert out.mutated_profile["motivation"] < 0.5


def test_intent_clarity_skipped_when_awareness_above_threshold() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(awareness=0.50),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "intent_clarity" not in names


# ---------------------------------------------------------------------------
# Positive trigger 4: positive_trust_boost
# ---------------------------------------------------------------------------


def test_positive_trust_boost_fires_when_known_brand_with_trial() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(trust=0.5),
        architect_outputs=_arch(bdm=0.90, free_trial_substitute=0.5),
        assumptions=[_assumption("We offer a free trial")],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_trust_boost" in names
    assert out.mutated_profile["trust"] > 0.5


def test_positive_trust_boost_skipped_without_trial() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(bdm=0.90),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_trust_boost" not in names


# ---------------------------------------------------------------------------
# Positive trigger 5: positive_value_confidence
# ---------------------------------------------------------------------------


def test_positive_value_confidence_fires_when_high_will_pay_and_disclosure() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(patience=0.5),
        architect_outputs=_arch(will_pay=0.75, disclosure=6.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_value_confidence" in names
    assert out.mutated_profile["patience_score"] > 0.5


def test_positive_value_confidence_skipped_when_will_pay_low() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(will_pay=0.40, disclosure=6.0),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_value_confidence" not in names


# ---------------------------------------------------------------------------
# Positive trigger 6: positive_awareness_boost
# ---------------------------------------------------------------------------


def test_positive_awareness_boost_fires_when_awareness_high() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(motivation=0.5),
        architect_outputs=_arch(awareness=0.85),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_awareness_boost" in names
    assert out.mutated_profile["motivation"] > 0.5


def test_positive_awareness_boost_skipped_when_awareness_below_threshold() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(awareness=0.50),
        assumptions=[],
    )
    names = [mu.trigger_name for mu in out.mutations_applied]
    assert "positive_awareness_boost" not in names


# ---------------------------------------------------------------------------
# Per-trait mutation cap
# ---------------------------------------------------------------------------


def test_negative_cap_holds_at_max_mutation_per_trait() -> None:
    """Even with trust_delta firing (-0.15) the cumulative drop ≤ 0.35."""
    from app.simulation.cognitive_state import (
        MAX_MUTATION_PER_TRAIT,
        CognitiveStateMutator,
    )

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.10, free_trial_substitute=0.0),
        assumptions=[],
    )
    delta = profile["trust"] - out.mutated_profile["trust"]
    assert delta <= MAX_MUTATION_PER_TRAIT + 1e-9


def test_positive_cap_holds_at_max_mutation_per_trait() -> None:
    from app.simulation.cognitive_state import (
        MAX_MUTATION_PER_TRAIT,
        CognitiveStateMutator,
    )

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.95),
        assumptions=[_assumption("free trial available")],
    )
    delta = out.mutated_profile["trust"] - profile["trust"]
    assert delta <= MAX_MUTATION_PER_TRAIT + 1e-9


def test_traits_floor_and_ceiling() -> None:
    """mutated_profile traits remain within [TRAIT_FLOOR, 1.0]."""
    from app.simulation.cognitive_state import TRAIT_FLOOR, CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.10, patience=0.10, motivation=0.10)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(
            bdm=0.10, free_trial_substitute=0.0,
            will_pay=0.10, disclosure=2.0, awareness=0.10,
        ),
        assumptions=[],
    )
    for trait in ("trust", "patience_score", "motivation"):
        assert out.mutated_profile[trait] >= TRAIT_FLOOR
        assert out.mutated_profile[trait] <= 1.0


# ---------------------------------------------------------------------------
# Aggregation + flags
# ---------------------------------------------------------------------------


def test_total_trust_delta_matches_profile_diff() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.10, free_trial_substitute=0.0),
        assumptions=[],
    )
    expected = round(out.mutated_profile["trust"] - profile["trust"], 4)
    assert out.total_trust_delta == expected


def test_total_frustration_matches_patience_diff() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(patience=0.6)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(will_pay=0.10, disclosure=2.0),
        assumptions=[],
    )
    expected = round(out.mutated_profile["patience_score"] - profile["patience_score"], 4)
    assert out.total_frustration == expected


def test_total_intent_drop_matches_motivation_diff() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(motivation=0.5)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(awareness=0.10),
        assumptions=[],
    )
    expected = round(out.mutated_profile["motivation"] - profile["motivation"], 4)
    assert out.total_intent_drop == expected


def test_any_mutation_fired_flag_correct() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    # No triggers fire: all metrics neutral, no trial, no assumptions.
    out = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(),
        assumptions=[],
    )
    assert out.any_mutation_fired is False
    assert out.mutations_applied == []

    # Force at least one trigger.
    out2 = m.apply(
        cluster_id="metro",
        agent_profile=_base_profile(),
        architect_outputs=_arch(awareness=0.10),
        assumptions=[],
    )
    assert out2.any_mutation_fired is True


# ---------------------------------------------------------------------------
# Profile immutability + edge cases
# ---------------------------------------------------------------------------


def test_original_profile_is_not_mutated() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5)
    snapshot = dict(profile)
    m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(bdm=0.10, free_trial_substitute=0.0),
        assumptions=[],
    )
    assert profile == snapshot


def test_non_numeric_profile_keys_are_ignored() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile: dict[str, Any] = {
        "trust": 0.5,
        "patience_score": 0.5,
        "motivation": 0.5,
        "label": "loving it",  # non-numeric — must be skipped
    }
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(),
        assumptions=[],
    )
    assert "label" not in out.mutated_profile


def test_all_triggers_can_coexist() -> None:
    """Stress test: with low bdm, low will_pay, low disclosure, low awareness
    + no trial → 3 negative triggers fire simultaneously and stack within
    the per-trait cap."""
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile(trust=0.5, patience=0.5, motivation=0.5)
    out = m.apply(
        cluster_id="metro",
        agent_profile=profile,
        architect_outputs=_arch(
            bdm=0.10, free_trial_substitute=0.0,
            will_pay=0.10, disclosure=2.0, awareness=0.10,
        ),
        assumptions=[],
    )
    names = sorted(mu.trigger_name for mu in out.mutations_applied)
    assert names == ["frustration", "intent_clarity", "trust_delta"]
    assert out.any_mutation_fired is True


def test_apply_is_deterministic() -> None:
    from app.simulation.cognitive_state import CognitiveStateMutator

    m = CognitiveStateMutator()
    profile = _base_profile()
    arch = _arch(bdm=0.10, free_trial_substitute=0.0, awareness=0.10)
    a = m.apply(cluster_id="c", agent_profile=profile, architect_outputs=arch, assumptions=[])
    b = m.apply(cluster_id="c", agent_profile=profile, architect_outputs=arch, assumptions=[])
    assert a.mutated_profile == b.mutated_profile
    assert a.total_trust_delta == b.total_trust_delta
