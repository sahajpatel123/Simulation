"""Tests for shared architect utilities in ``app.simulation.architects.utils``.

Locks down the helper extraction so subsequent refactors can rely on it.
"""
from __future__ import annotations

from app.simulation.architects.utils import (
    contains_phrase,
    contains_word,
    extract_assumption_signals,
    extract_complexity,
)


def _assumption(text: str) -> dict:
    return {"text": text}


def test_contains_phrase_matches_substring() -> None:
    assumptions = [_assumption("Allow 30 day return policy"), _assumption("Express checkout")]

    assert contains_phrase(assumptions, ["30 day"]) is True
    assert contains_phrase(assumptions, ["return policy"]) is True


def test_contains_phrase_returns_false_when_missing() -> None:
    assert contains_phrase([_assumption("Fast shipping")], ["no cost emi"]) is False


def test_contains_phrase_returns_false_for_empty_assumptions() -> None:
    assert contains_phrase([], ["anything"]) is False


def test_contains_word_matches_whole_token() -> None:
    assumptions = [_assumption("Customers can use Simpl at checkout")]

    assert contains_word(assumptions, ["simpl"]) is True
    assert contains_word(assumptions, ["lazypay", "simpl"]) is True


def test_contains_word_does_not_match_substring() -> None:
    assumptions = [
        _assumption("The setup is simple enough for first-time users."),
        _assumption("A simple dashboard with no clutter."),
    ]

    assert contains_word(assumptions, ["simpl"]) is False


def test_contains_word_is_case_insensitive() -> None:
    assert contains_word([_assumption("LazyPay is supported")], ["lazypay"]) is True


def test_contains_word_returns_false_for_empty_assumptions() -> None:
    assert contains_word([], ["bnpl"]) is False


def test_contains_word_handles_punctuation_boundary() -> None:
    assert contains_word([_assumption("Pay-later options exist.")], ["paylater", "bnpl"]) is False
    assert contains_word([_assumption("Pay later options exist.")], ["paylater"]) is False


def test_extract_complexity_defaults_to_neutral() -> None:
    assert extract_complexity([]) == 0.5
    assert extract_complexity([_assumption("We will offer a flexible plan")]) == 0.5


def test_extract_complexity_flags_complex_keywords() -> None:
    assert extract_complexity([_assumption("Multi-step enterprise workflow")]) == 0.8


def test_extract_complexity_flags_simple_keywords() -> None:
    assert extract_complexity([_assumption("A seamless experience in 2 minute setup")]) == 0.25


def test_extract_assumption_signals_default() -> None:
    signals = extract_assumption_signals([])

    assert signals == {
        "urgency_stated": 0.5,
        "switching_stated": 0.5,
        "regulatory_dep": False,
        "seasonal": False,
    }


def test_extract_assumption_signals_detects_urgency_and_switching() -> None:
    signals = extract_assumption_signals([
        _assumption("This is a critical pain point"),
        _assumption("Customers will switch from existing tools"),
        _assumption("Users want to replace the incumbent tool"),
    ])

    assert signals["urgency_stated"] == 0.80
    assert signals["switching_stated"] == 0.70


def test_extract_assumption_signals_detects_regulatory_and_seasonal() -> None:
    signals = extract_assumption_signals([
        _assumption("Need SEBI approval before launch"),
        _assumption("Launch during the Diwali festival window"),
    ])

    assert signals["regulatory_dep"] is True
    assert signals["seasonal"] is True


def test_extract_assumption_signals_can_demote_urgency() -> None:
    signals = extract_assumption_signals([
        _assumption("Feature is nice to have for some users"),
    ])

    assert signals["urgency_stated"] == 0.25
