"""Tests for WhatIfSummary.has_direction()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary


def test_has_direction_false_when_breakdown_empty() -> None:
    assert WhatIfSummary().has_direction("POSITIVE") is False


def test_has_direction_true_for_nonzero_count() -> None:
    summary = WhatIfSummary(direction_breakdown={"POSITIVE": 3})
    assert summary.has_direction("POSITIVE") is True


def test_has_direction_false_for_zero_count() -> None:
    summary = WhatIfSummary(direction_breakdown={"POSITIVE": 0})
    assert summary.has_direction("POSITIVE") is False


def test_has_direction_unknown_label() -> None:
    summary = WhatIfSummary(direction_breakdown={"POSITIVE": 2})
    assert summary.has_direction("NEUTRAL") is False
