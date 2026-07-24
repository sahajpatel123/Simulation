"""Cross-helper consistency contract for WhatIfOut string surfaces."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut


def test_to_log_line_includes_direction_word_and_delta_pct() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=12.5,
        conversion_delta=0.05,
        meta={"dominant_direction": "POSITIVE", "sensitivity_label": "HIGH"},
    )

    line = out.to_log_line()

    assert "direction=POSITIVE" in line
    assert "+12.50%" in line


def test_str_matches_to_log_line_for_positive() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=10.0,
        conversion_delta=0.05,
    )

    assert str(out) == out.to_log_line()


def test_compact_delta_arrow_matches_direction_arrow() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=-3.5,
        conversion_delta=-0.05,
    )

    assert out.direction_arrow() == "↓"
    assert out.compact_delta().startswith("↓")


def test_log_line_direction_label_agreement() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        conversion_delta_pct=20.0,
        conversion_delta=0.05,
        meta={"dominant_direction": "POSITIVE", "sensitivity_label": "CRITICAL"},
    )

    line = out.to_log_line()
    assert "direction=POSITIVE" in line
    assert "sensitivity=CRITICAL" in line
    assert out.direction_label() == "improvement"