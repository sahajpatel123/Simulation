"""Tests for WhatIfOut.compact_delta()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_compact_delta_for_improvement() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=12.5,
        conversion_delta=0.05,
    )

    assert out.compact_delta() == "↑ +12.50%"


def test_compact_delta_for_regression() -> None:
    out = WhatIfOut(
        simulation_id=99,
        project_id=99,
        conversion_delta_pct=-7.5,
        conversion_delta=-0.05,
    )

    assert out.compact_delta() == "↓ -7.50%"


def test_compact_delta_for_neutral() -> None:
    out = WhatIfOut(
        simulation_id=7,
        project_id=7,
        conversion_delta_pct=0.0,
        conversion_delta=0.0,
    )

    assert out.compact_delta() == "→ +0.00%"


def test_compact_delta_omits_simulation_id() -> None:
    out = WhatIfOut(
        simulation_id=42,
        project_id=42,
        conversion_delta_pct=5.0,
        conversion_delta=0.02,
    )
    assert "42" not in out.compact_delta()