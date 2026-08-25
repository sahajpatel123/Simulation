"""Tests for WhatIfSummary.top_category_name()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfSummary, WhatIfSummaryCategory


def test_top_category_name_none_when_empty() -> None:
    assert WhatIfSummary().top_category_name() is None


def test_top_category_name_returns_only_category() -> None:
    summary = WhatIfSummary(
        top_categories=[WhatIfSummaryCategory(category="pricing", count=2)],
    )

    assert summary.top_category_name() == "pricing"


def test_top_category_name_returns_first_when_multiple() -> None:
    summary = WhatIfSummary(
        top_categories=[
            WhatIfSummaryCategory(category="pricing", count=5),
            WhatIfSummaryCategory(category="trust", count=3),
        ],
    )

    assert summary.top_category_name() == "pricing"
