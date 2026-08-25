"""Tests for WhatIfOut.to_one_line()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_to_one_line_for_improvement() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=12.5,
        conversion_delta=0.05,
    )

    assert out.to_one_line() == "sim=1 ↑ +12.50%"


def test_to_one_line_for_regression() -> None:
    out = WhatIfOut(
        simulation_id=42,
        project_id=1,
        conversion_delta_pct=-7.5,
        conversion_delta=-0.05,
    )

    assert out.to_one_line() == "sim=42 ↓ -7.50%"


def test_to_one_line_for_neutral() -> None:
    out = WhatIfOut(
        simulation_id=7,
        project_id=1,
        conversion_delta_pct=0.0,
        conversion_delta=0.0,
    )

    assert out.to_one_line() == "sim=7 → +0.00%"


def test_to_one_line_returns_string() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1)
    assert isinstance(out.to_one_line(), str)
