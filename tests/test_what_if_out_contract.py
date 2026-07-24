"""Contract test: every WhatIfOut helper method returns the expected type."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation


def _scenario() -> WhatIfOut:
    return WhatIfOut(
        simulation_id=1,
        project_id=2,
        base_conversion_rate=0.04,
        projected_conversion_rate=0.05,
        conversion_delta=0.01,
        conversion_delta_pct=25.0,
        recommendations=[
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ],
        meta={"dominant_direction": "POSITIVE", "sensitivity_label": "HIGH", "matched_keyword_categories": ["pricing"]},
    )


def test_summary_returns_dict_with_documented_keys() -> None:
    summary = _scenario().summary()

    assert isinstance(summary, dict)
    assert summary["simulation_id"] == 1
    assert summary["matched_keyword_categories"] == ["pricing"]


def test_to_log_line_returns_string() -> None:
    line = _scenario().to_log_line()
    assert isinstance(line, str)
    assert "sim=1" in line


def test_has_positive_negative_neutral_predicates_are_bool() -> None:
    out = _scenario()
    assert isinstance(out.has_positive_delta(), bool)
    assert isinstance(out.has_negative_delta(), bool)
    assert isinstance(out.is_neutral(), bool)


def test_direction_arrow_returns_one_of_three_glyphs() -> None:
    arrow = _scenario().direction_arrow()
    assert arrow in {"↑", "↓", "→"}


def test_direction_label_returns_one_of_three_words() -> None:
    label = _scenario().direction_label()
    assert label in {"improvement", "regression", "neutral"}


def test_has_category_returns_bool() -> None:
    out = _scenario()
    assert isinstance(out.has_category("pricing"), bool)
    assert isinstance(out.has_category("ux"), bool)


def test_to_csv_header_returns_list_of_strings() -> None:
    header = WhatIfOut.to_csv_header()
    assert isinstance(header, list)
    assert all(isinstance(name, str) for name in header)


def test_to_csv_row_returns_list_of_strings_aligned_with_header() -> None:
    out = _scenario()
    row = out.to_csv_row()
    assert isinstance(row, list)
    assert len(row) == len(WhatIfOut.to_csv_header())
    assert all(isinstance(value, str) for value in row)


def test_top_recommendation_returns_recommendation_or_none() -> None:
    out = _scenario()
    top = out.top_recommendation()
    assert top is not None
    assert isinstance(top, WhatIfRecommendation)
    assert top.priority == 1


def test_str_matches_log_line() -> None:
    out = _scenario()
    assert str(out) == out.to_log_line()