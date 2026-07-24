"""Consistency tests between direction_arrow() and the delta predicates."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def _check(delta: float) -> tuple[str, bool, bool, bool]:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=delta)
    return (
        out.direction_arrow(),
        out.has_positive_delta(),
        out.has_negative_delta(),
        out.is_neutral(),
    )


def test_arrow_up_matches_positive_predicate() -> None:
    arrow, pos, neg, neu = _check(0.05)
    assert arrow == "↑"
    assert pos is True
    assert neg is False
    assert neu is False


def test_arrow_down_matches_negative_predicate() -> None:
    arrow, pos, neg, neu = _check(-0.05)
    assert arrow == "↓"
    assert pos is False
    assert neg is True
    assert neu is False


def test_arrow_right_matches_neutral_predicate() -> None:
    arrow, pos, neg, neu = _check(0.0)
    assert arrow == "→"
    assert pos is False
    assert neg is False
    assert neu is True


def test_arrow_at_positive_tolerance_boundary() -> None:
    arrow, _pos, _neg, neu = _check(1e-12)
    assert arrow == "→"
    assert neu is True