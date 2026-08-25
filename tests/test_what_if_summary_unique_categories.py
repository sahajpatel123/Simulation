"""Tests for WhatIfSummary.unique_categories()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary, WhatIfSummaryCategory


def test_unique_categories_empty_when_no_top_categories() -> None:
    assert WhatIfSummary().unique_categories() == []


def test_unique_categories_returns_sorted_distinct_names() -> None:
    summary = WhatIfSummary(
        top_categories=[
            WhatIfSummaryCategory(category="pricing", count=3),
            WhatIfSummaryCategory(category="trust", count=1),
            WhatIfSummaryCategory(category="pricing", count=2),  # duplicate name
        ],
    )

    assert summary.unique_categories() == ["pricing", "trust"]


def test_unique_categories_handles_single_category() -> None:
    summary = WhatIfSummary(
        top_categories=[WhatIfSummaryCategory(category="ux", count=1)],
    )

    assert summary.unique_categories() == ["ux"]
