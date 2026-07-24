"""Tests for format_delta_pct helper."""
from __future__ import annotations

from app.simulation.what_if import format_delta_pct


def test_positive_value_has_plus_sign() -> None:
    assert format_delta_pct(12.34) == "+12.34%"


def test_negative_value_has_minus_sign() -> None:
    assert format_delta_pct(-3.5) == "-3.50%"


def test_zero_value_has_plus_sign_by_convention() -> None:
    assert format_delta_pct(0.0) == "+0.00%"


def test_custom_decimals() -> None:
    assert format_delta_pct(7.12345, decimals=3) == "+7.123%"
    assert format_delta_pct(-1.2, decimals=0) == "-1%"


def test_handles_large_values() -> None:
    assert format_delta_pct(1234.5) == "+1234.50%"