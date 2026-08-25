"""Schema-level round-trip tests for the typed what-if Pydantic models.

Locks down default values and JSON-serialisation shape so API consumers can
rely on the response contract.
"""
from __future__ import annotations

from app.schemas.what_if import (
    WhatIfDiff,
    WhatIfSummary,
    WhatIfSummaryCategory,
)


def test_what_if_summary_defaults() -> None:
    summary = WhatIfSummary()

    assert summary.scenario_count == 0
    assert summary.avg_delta == 0.0
    assert summary.best_delta == 0.0
    assert summary.worst_delta == 0.0
    assert summary.direction_breakdown == {}
    assert summary.top_categories == []


def test_what_if_summary_round_trip() -> None:
    summary = WhatIfSummary(
        scenario_count=3,
        avg_delta=0.02,
        best_delta=0.10,
        worst_delta=-0.05,
        direction_breakdown={"POSITIVE": 1, "NEGATIVE": 2},
        top_categories=[WhatIfSummaryCategory(category="pricing", count=2)],
    )

    dumped = summary.model_dump()
    rebuilt = WhatIfSummary.model_validate(dumped)

    assert rebuilt == summary
    assert dumped["direction_breakdown"] == {"POSITIVE": 1, "NEGATIVE": 2}
    assert dumped["top_categories"][0]["category"] == "pricing"


def test_what_if_diff_defaults() -> None:
    diff = WhatIfDiff(
        base_simulation_id=1,
        other_simulation_id=2,
    )

    assert diff.base_new_assumption_count == 0
    assert diff.other_new_assumption_count == 0
    assert diff.base_delta == 0.0
    assert diff.other_delta == 0.0
    assert diff.delta_difference == 0.0
    assert diff.shared_keyword_categories == []
    assert diff.base_only_categories == []
    assert diff.other_only_categories == []


def test_what_if_diff_round_trip() -> None:
    diff = WhatIfDiff(
        base_simulation_id=10,
        other_simulation_id=20,
        base_new_assumption_count=3,
        other_new_assumption_count=2,
        base_delta=-0.04,
        other_delta=0.02,
        delta_difference=0.06,
        shared_keyword_categories=["pricing"],
        base_only_categories=["ux"],
        other_only_categories=["trust"],
    )

    dumped = diff.model_dump()
    rebuilt = WhatIfDiff.model_validate(dumped)

    assert rebuilt == diff
    assert dumped["shared_keyword_categories"] == ["pricing"]
