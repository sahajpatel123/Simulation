"""Tests for WhatIfOut delta predicates."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_has_positive_delta_for_positive() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.05)
    assert out.has_positive_delta() is True
    assert out.has_negative_delta() is False
    assert out.is_neutral() is False


def test_has_negative_delta_for_negative() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.03)
    assert out.has_negative_delta() is True
    assert out.has_positive_delta() is False


def test_is_neutral_for_zero_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.0)
    assert out.is_neutral() is True
    assert out.has_positive_delta() is False
    assert out.has_negative_delta() is False


def test_is_neutral_for_tiny_delta() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=1e-12)
    assert out.is_neutral() is True


def test_predicates_are_mutually_exclusive() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=0.1)
    flags = [out.has_positive_delta(), out.has_negative_delta(), out.is_neutral()]
    assert sum(flags) == 1


def test_predicates_mutually_exclusive_for_negative() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta=-0.1)
    flags = [out.has_positive_delta(), out.has_negative_delta(), out.is_neutral()]
    assert sum(flags) == 1
