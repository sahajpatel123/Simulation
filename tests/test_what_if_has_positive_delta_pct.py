"""Tests for WhatIfOut.has_positive_delta_pct()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_has_positive_delta_pct_true_for_positive() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta_pct=12.5)
    assert out.has_positive_delta_pct() is True


def test_has_positive_delta_pct_false_for_negative() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta_pct=-12.5)
    assert out.has_positive_delta_pct() is False


def test_has_positive_delta_pct_false_for_zero() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1, conversion_delta_pct=0.0)
    assert out.has_positive_delta_pct() is False
