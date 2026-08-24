"""Tests for ``app.simulation.scored_assumption.detect_contradictions``.

The hard/soft contradiction table drives the signal-quality penalty and the
clarifying questions shown to founders, so the matching logic must stay stable.
"""
from __future__ import annotations

from app.simulation.scored_assumption import detect_contradictions


def test_no_assumptions_returns_zero_hard_and_empty_flags() -> None:
    hard, soft = detect_contradictions([])
    assert hard == 0
    assert soft == []


def test_hard_contradiction_free_plus_subscription() -> None:
    hard, _ = detect_contradictions([
        "Free product for everyone",
        "Subscription revenue drives the business",
    ])
    assert hard == 1


def test_hard_contradiction_physical_hardware_plus_software_only() -> None:
    hard, _ = detect_contradictions([
        "We sell physical hardware to gyms",
        "Pure software only — no shipping",
    ])
    assert hard == 1


def test_hard_contradiction_b2c_plus_enterprise() -> None:
    hard, _ = detect_contradictions([
        "B2C consumer focus with self-serve onboarding",
        "Built for enterprise procurement cycles",
    ])
    assert hard == 1


def test_multiple_hard_contradictions_counted_separately() -> None:
    hard, _ = detect_contradictions([
        "Free product for everyone",
        "Subscription revenue drives the business",
        "Offline only with no connectivity",
        "Cloud sync across all devices",
    ])
    assert hard == 2


def test_soft_flag_for_premium_plus_tier3() -> None:
    _, soft = detect_contradictions([
        "Premium pricing across all tiers",
        "Tier-3 primary market",
    ])
    assert any("premium pricing" in flag for flag in soft)


def test_soft_flag_for_simple_plus_extensive() -> None:
    _, soft = detect_contradictions([
        "Simple product focused on one job",
        "Extensive feature list across workflows",
    ])
    assert any("simple product" in flag for flag in soft)


def test_soft_flag_for_freemium_plus_high_cac() -> None:
    _, soft = detect_contradictions([
        "Freemium model with self-serve",
        "High CAC tolerance for enterprise sales",
    ])
    assert any("freemium model" in flag for flag in soft)


def test_no_contradictions_when_patterns_absent() -> None:
    hard, soft = detect_contradictions([
        "We sell a SaaS dashboard",
        "Target audience is small business owners",
    ])
    assert hard == 0
    assert soft == []


def test_assumptions_are_case_insensitive() -> None:
    hard, _ = detect_contradictions([
        "FREE PRODUCT for all users",
        "subscription revenue main income",
    ])
    assert hard == 1
