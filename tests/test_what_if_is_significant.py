"""Tests for WhatIfOut.is_significant()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_is_significant_true_for_large_positive_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.05)
    assert out.is_significant() is True


def test_is_significant_true_for_large_negative_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.05)
    assert out.is_significant() is True


def test_is_significant_false_for_small_delta_with_default_threshold() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.005)
    assert out.is_significant() is False


def test_is_significant_false_for_zero_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.0)
    assert out.is_significant() is False


def test_is_significant_custom_threshold() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.005)
    assert out.is_significant(threshold=0.001) is True
    assert out.is_significant(threshold=0.01) is False


def test_is_significant_threshold_uses_absolute_value() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.05)
    assert out.is_significant(threshold=-0.01) is True
