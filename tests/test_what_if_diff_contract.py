"""Contract tests for the WhatIfDiff schema surface."""
from __future__ import annotations

from app.schemas.what_if import WhatIfDiff, WhatIfOut, WhatIfRecommendation


def _diff(delta_difference: float = 0.05) -> WhatIfDiff:
    return WhatIfDiff(
        base_simulation_id=1,
        other_simulation_id=2,
        base_delta=0.01,
        other_delta=0.06,
        delta_difference=delta_difference,
        shared_keyword_categories=["pricing"],
        base_only_categories=[],
        other_only_categories=["trust"],
    )


def test_defaults_apply_when_only_required_fields_provided() -> None:
    diff = WhatIfDiff(base_simulation_id=1, other_simulation_id=2)
    assert diff.base_new_assumption_count == 0
    assert diff.other_new_assumption_count == 0
    assert diff.base_delta == 0.0
    assert diff.other_delta == 0.0
    assert diff.delta_difference == 0.0
    assert diff.shared_keyword_categories == []
    assert diff.base_only_categories == []
    assert diff.other_only_categories == []


def test_direction_label_returns_documented_label() -> None:
    assert _diff(0.05).direction_label() == "improvement"
    assert _diff(-0.05).direction_label() == "regression"
    assert _diff(0.0).direction_label() == "neutral"


def test_direction_label_uses_threshold_matching_other_helpers() -> None:
    diff = _diff(1e-12)
    assert diff.direction_label() == "neutral"


def test_fields_are_serialisable_to_dict() -> None:
    diff = _diff(0.05)
    dumped = diff.model_dump()

    assert dumped["base_simulation_id"] == 1
    assert dumped["other_simulation_id"] == 2
    assert dumped["delta_difference"] == 0.05
    assert dumped["shared_keyword_categories"] == ["pricing"]


def test_round_trip_validation() -> None:
    diff = _diff(0.05)
    rebuilt = WhatIfDiff.model_validate(diff.model_dump())
    assert rebuilt == diff


def test_what_if_out_has_recommendations_predicate_round_trip() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[WhatIfRecommendation(priority=1, title="a", rationale="r")],
    )

    assert out.has_recommendations() is True
