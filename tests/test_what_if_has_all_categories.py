"""Tests for WhatIfOut.has_all_categories()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def _scenario(categories: list[str]) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=1,
        project_id=1,
        meta={"matched_keyword_categories": categories},
    )


def test_has_all_categories_true_when_all_present() -> None:
    assert _scenario(["pricing", "trust"]).has_all_categories(["pricing"]) is True
    assert _scenario(["pricing", "trust"]).has_all_categories(["pricing", "trust"]) is True


def test_has_all_categories_false_when_any_missing() -> None:
    assert _scenario(["pricing"]).has_all_categories(["pricing", "trust"]) is False
    assert _scenario([]).has_all_categories(["pricing"]) is False


def test_has_all_categories_true_when_target_empty() -> None:
    """Vacuous truth: empty target returns True so callers can pass defaults."""
    assert _scenario([]).has_all_categories([]) is True
    assert _scenario(["pricing"]).has_all_categories([]) is True


def test_has_all_categories_uses_set_semantics() -> None:
    """Order and duplicates in target do not matter."""
    scenario = _scenario(["pricing", "trust", "ux"])

    assert scenario.has_all_categories(["trust", "pricing", "ux"]) is True
    assert scenario.has_all_categories(["trust", "trust"]) is True