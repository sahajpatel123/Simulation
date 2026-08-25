"""Tests for the format_categories helper."""
from __future__ import annotations

from app.simulation.what_if import format_categories


def test_empty_list_returns_default_none() -> None:
    assert format_categories([]) == "none"


def test_none_input_returns_default_none() -> None:
    assert format_categories(None) == "none"


def test_single_category() -> None:
    assert format_categories(["pricing"]) == "pricing"


def test_multiple_categories_joined_with_comma() -> None:
    assert format_categories(["pricing", "trust", "ux"]) == "pricing,trust,ux"


def test_custom_empty_placeholder() -> None:
    assert format_categories([], empty="—") == "—"
    assert format_categories(None, empty="none-set") == "none-set"
