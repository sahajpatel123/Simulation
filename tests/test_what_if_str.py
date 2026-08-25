"""Tests for WhatIfOut.__str__ delegating to to_log_line."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_str_delegates_to_to_log_line() -> None:
    out = WhatIfOut(
        simulation_id=7,
        project_id=11,
        conversion_delta=0.02,
        conversion_delta_pct=12.5,
        meta={"dominant_direction": "POSITIVE", "sensitivity_label": "HIGH"},
    )

    assert str(out) == out.to_log_line()


def test_str_includes_sim_id_and_direction() -> None:
    out = WhatIfOut(
        simulation_id=99,
        project_id=99,
        meta={"dominant_direction": "NEGATIVE", "sensitivity_label": "CRITICAL"},
    )

    text = str(out)
    assert "sim=99" in text
    assert "direction=NEGATIVE" in text
    assert "sensitivity=CRITICAL" in text


def test_str_falls_back_to_defaults() -> None:
    out = WhatIfOut(simulation_id=1, project_id=1)

    text = str(out)

    assert "direction=NEUTRAL" in text
    assert "sensitivity=NONE" in text
