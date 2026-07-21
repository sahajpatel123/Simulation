"""
Tests for simulation_report.py helpers (cycle 38 report-helper-tests).

The report builder depends on a few small, deterministic helpers that can
be tested without spinning up ReportLab canvas / PDF rendering:

  1. ``_severity_color`` maps severity strings to brand colours.
  2. ``_top_channel_label`` defensively extracts the top channel name.
  3. The brand colour constants are real, valid Color objects.
  4. ``_styles`` returns the documented custom ParagraphStyle keys.
"""
from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# _severity_color
# ---------------------------------------------------------------------------


def test_severity_color_returns_critical_red() -> None:
    from app.reports.simulation_report import (
        THECEE_RED,
        _severity_color,
    )

    assert _severity_color("CRITICAL") == THECEE_RED


def test_severity_color_returns_warning_amber() -> None:
    from app.reports.simulation_report import (
        THECEE_AMBER,
        _severity_color,
    )

    assert _severity_color("WARNING") == THECEE_AMBER


def test_severity_color_returns_info_green() -> None:
    from app.reports.simulation_report import (
        THECEE_GREEN,
        _severity_color,
    )

    assert _severity_color("INFO") == THECEE_GREEN


def test_severity_color_unknown_falls_back_to_dark() -> None:
    from app.reports.simulation_report import (
        THECEE_DARK,
        _severity_color,
    )

    # Unknown / lowercase / None → default dark.
    assert _severity_color("UNKNOWN") == THECEE_DARK
    assert _severity_color("critical") == THECEE_DARK  # case-sensitive lookup
    assert _severity_color("") == THECEE_DARK
    assert _severity_color(None) == THECEE_DARK  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _top_channel_label
# ---------------------------------------------------------------------------


def test_top_channel_label_returns_first_channel_dict() -> None:
    from app.reports.simulation_report import _top_channel_label

    channel_data: dict[str, Any] = {
        "market_channel_ranking": [
            {"channel": "SEO"},
            {"channel": "PAID_SOCIAL"},
        ]
    }
    assert _top_channel_label(channel_data) == "SEO"


def test_top_channel_label_handles_list_tuple_rows() -> None:
    """Older payloads may pass rows as ``[name, share]`` tuples."""
    from app.reports.simulation_report import _top_channel_label

    assert (
        _top_channel_label({"market_channel_ranking": [["DIRECT", 0.4], ["REFERRAL", 0.3]]})
        == "DIRECT"
    )


def test_top_channel_label_returns_dash_for_empty_ranking() -> None:
    from app.reports.simulation_report import _top_channel_label

    assert _top_channel_label({"market_channel_ranking": []}) == "—"
    assert _top_channel_label({"market_channel_ranking": None}) == "—"


def test_top_channel_label_returns_dash_when_key_missing() -> None:
    from app.reports.simulation_report import _top_channel_label

    assert _top_channel_label({}) == "—"


def test_top_channel_label_returns_dash_for_unexpected_first_entry_shape() -> None:
    """If the first row is neither a dict nor a list/tuple, fall back gracefully."""
    from app.reports.simulation_report import _top_channel_label

    assert _top_channel_label({"market_channel_ranking": [42]}) == "—"
    assert _top_channel_label({"market_channel_ranking": [None]}) == "—"


def test_top_channel_label_short_tuple_returns_dash() -> None:
    """Empty tuple/list has no first element to extract."""
    from app.reports.simulation_report import _top_channel_label

    assert _top_channel_label({"market_channel_ranking": [[]]}) == "—"


# ---------------------------------------------------------------------------
# Brand color constants
# ---------------------------------------------------------------------------


def test_brand_colors_are_valid_reportlab_colors() -> None:
    """Each brand constant must be a real reportlab Color (not None)."""
    from reportlab.lib import colors

    from app.reports.simulation_report import (
        THECEE_AMBER,
        THECEE_BLUE,
        THECEE_DARK,
        THECEE_GREEN,
        THECEE_LIGHT,
        THECEE_RED,
    )

    for c in (THECEE_AMBER, THECEE_BLUE, THECEE_DARK, THECEE_GREEN, THECEE_LIGHT, THECEE_RED):
        assert isinstance(c, colors.Color)


def test_brand_colors_are_distinct() -> None:
    """No two brand colours should resolve to the same hex."""
    from app.reports.simulation_report import (
        THECEE_AMBER,
        THECEE_BLUE,
        THECEE_DARK,
        THECEE_GREEN,
        THECEE_LIGHT,
        THECEE_RED,
    )

    seen = {
        THECEE_AMBER.hexval(),
        THECEE_BLUE.hexval(),
        THECEE_DARK.hexval(),
        THECEE_GREEN.hexval(),
        THECEE_LIGHT.hexval(),
        THECEE_RED.hexval(),
    }
    assert len(seen) == 6


# ---------------------------------------------------------------------------
# _styles
# ---------------------------------------------------------------------------


def test_styles_returns_expected_custom_keys() -> None:
    from app.reports.simulation_report import _styles

    base, custom = _styles()
    expected = {
        "ReportTitle",
        "SectionHeader",
        "SubHeader",
        "Body",
        "Metric",
        "Caption",
    }
    assert set(custom.keys()) == expected
    # base is the reportlab sample stylesheet; sanity-check a couple of keys.
    assert "Normal" in base
    assert "Title" in base


def test_styles_custom_keys_are_paragraph_styles() -> None:
    from reportlab.lib.styles import ParagraphStyle

    from app.reports.simulation_report import _styles

    _base, custom = _styles()
    for style in custom.values():
        assert isinstance(style, ParagraphStyle)
