"""Regression test: to_log_line() uses the canonical format_delta_pct formatter."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut
from app.simulation.what_if import format_delta_pct


def test_log_line_uses_format_delta_pct_for_positive() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=12.34,
    )

    assert format_delta_pct(12.34) in out.to_log_line()


def test_log_line_uses_format_delta_pct_for_negative() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=-7.5,
    )

    assert format_delta_pct(-7.5) in out.to_log_line()