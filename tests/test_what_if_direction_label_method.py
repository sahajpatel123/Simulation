"""Tests for WhatIfOut.direction_label() method."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_direction_label_improvement_for_positive() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.1)
    assert out.direction_label() == "improvement"


def test_direction_label_regression_for_negative() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.1)
    assert out.direction_label() == "regression"


def test_direction_label_neutral_for_zero() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.0)
    assert out.direction_label() == "neutral"


def test_direction_label_agrees_with_direction_arrow_label_mapping() -> None:
    for delta in (0.05, -0.05, 0.0, 1e-12):
        out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=delta)
        arrow = out.direction_arrow()
        label = out.direction_label()
        if arrow == "↑":
            assert label == "improvement"
        elif arrow == "↓":
            assert label == "regression"
        else:
            assert label == "neutral"
