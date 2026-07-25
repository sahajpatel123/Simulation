"""Tests for WhatIfSummary.top_category_count()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary, WhatIfSummaryCategory


def test_top_category_count_zero_when_empty() -> None:
    assert WhatIfSummary().top_category_count() == 0


def test_top_category_count_returns_only_category() -> None:
    summary = WhatIfSummary(
        top_categories=[WhatIfSummaryCategory(category="pricing", count=2)],
    )

    assert summary.top_category_count() == 2


def test_top_category_count_returns_first_when_multiple() -> None:
    summary = WhatIfSummary(
        top_categories=[
            WhatIfSummaryCategory(category="pricing", count=5),
            WhatIfSummaryCategory(category="trust", count=3),
        ],
    )

    assert summary.top_category_count() == 5