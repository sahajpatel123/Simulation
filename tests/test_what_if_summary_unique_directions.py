"""Tests for WhatIfSummary.unique_directions()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary


def test_unique_directions_empty_when_breakdown_empty() -> None:
    assert WhatIfSummary().unique_directions() == []


def test_unique_directions_returns_sorted_labels() -> None:
    summary = WhatIfSummary(
        direction_breakdown={"POSITIVE": 2, "NEGATIVE": 3, "NEUTRAL": 1},
    )

    assert summary.unique_directions() == ["NEGATIVE", "NEUTRAL", "POSITIVE"]


def test_unique_directions_excludes_zero_counts() -> None:
    summary = WhatIfSummary(
        direction_breakdown={"POSITIVE": 0, "NEGATIVE": 2, "NEUTRAL": 0},
    )

    assert summary.unique_directions() == ["NEGATIVE"]
