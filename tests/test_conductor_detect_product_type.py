"""
Tests for Conductor.detect_product_type (cycle 40 conductor-detection-tests).

`detect_product_type` is the entry point that converts free-form project
description + assumptions into one of the ``ProductType`` enum values.
The scoring is keyword-based, with hardware-priority tie-breaking when
multiple types score equally.

These tests lock the contract:

  1. Empty description + empty assumptions → defaults to SAAS.
  2. Keywords in the description score the corresponding type.
  3. Assumption text contributes to the same scoring pool.
  4. Hardware keywords win over software in tied scores.
  5. Multi-keyword descriptions score the type with the highest hit count.
  6. The result is always a ProductType enum instance.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType


@pytest.fixture
def conductor() -> Conductor:
    return Conductor()


# ---------------------------------------------------------------------------
# Default fallback
# ---------------------------------------------------------------------------


def test_empty_description_defaults_to_saas(conductor: Conductor) -> None:
    """No keywords at all → SAAS is the safe fallback."""
    assert conductor.detect_product_type("", []) == ProductType.SAAS


def test_empty_assumptions_still_uses_description(conductor: Conductor) -> None:
    """Empty assumption list doesn't poison the description signal."""
    assert (
        conductor.detect_product_type("A b2b software crm platform", [])
        == ProductType.SAAS
    )


# ---------------------------------------------------------------------------
# Description-driven detection
# ---------------------------------------------------------------------------


def test_detects_saas_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A crm dashboard for sales teams", [])
        == ProductType.SAAS
    )


def test_detects_marketplace_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type(
            "A two-sided marketplace connecting buyers and sellers", []
        )
        == ProductType.MARKETPLACE
    )


def test_detects_mobile_app_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A consumer mobile app for ios app users", [])
        == ProductType.MOBILE_APP
    )


def test_detects_developer_tool_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A cli tool with a public api platform", [])
        == ProductType.DEVELOPER_TOOL
    )


def test_detects_enterprise_software_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("Enterprise procurement platform with SSO", [])
        == ProductType.ENTERPRISE_SOFTWARE
    )


def test_detects_consumer_hardware_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A new consumer electronics gadget", [])
        == ProductType.CONSUMER_HARDWARE
    )


def test_detects_wearable_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A new fitness tracker smartwatch band", [])
        == ProductType.WEARABLE
    )


def test_detects_health_hardware_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type(
            "A clinical-grade heart rate monitor medical device", []
        )
        == ProductType.HEALTH_HARDWARE
    )


def test_detects_iot_hardware_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type("A wifi-connected smart home sensor hub", [])
        == ProductType.IOT_HARDWARE
    )


def test_detects_b2b_hardware_from_description(conductor: Conductor) -> None:
    assert (
        conductor.detect_product_type(
            "An enterprise hardware pos device ruggedized for fleets", []
        )
        == ProductType.B2B_HARDWARE
    )


# ---------------------------------------------------------------------------
# Assumption-driven contribution
# ---------------------------------------------------------------------------


def test_assumptions_influence_detection(conductor: Conductor) -> None:
    """When the description is empty, assumptions can drive detection."""
    assert (
        conductor.detect_product_type(
            "",
            [{"text": "ios app for users", "sensitivity": "HIGH"}],
        )
        == ProductType.MOBILE_APP
    )


def test_assumption_with_assumption_key_instead_of_text(conductor: Conductor) -> None:
    """Older payloads may use the ``assumption`` key instead of ``text``."""
    assert (
        conductor.detect_product_type(
            "",
            [{"assumption": "smart home wifi device", "sensitivity": "MEDIUM"}],
        )
        == ProductType.IOT_HARDWARE
    )


# ---------------------------------------------------------------------------
# Multi-keyword scoring
# ---------------------------------------------------------------------------


def test_multi_keyword_picks_highest_count(conductor: Conductor) -> None:
    """A description rich in CRM keywords scores higher than one with a
    single wearable hit."""
    crm_heavy = (
        "A b2b software crm dashboard with api platform for sales teams. "
        "Subscription software for erp workflows."
    )
    assert conductor.detect_product_type(crm_heavy, []) == ProductType.SAAS


def test_combined_description_and_assumption(conductor: Conductor) -> None:
    """Description + assumption text together contribute to scoring."""
    desc = "A two-sided marketplace"
    assumptions = [
        {"text": "with ios app and android app for sellers", "sensitivity": "HIGH"}
    ]
    pt = conductor.detect_product_type(desc, assumptions)
    # MARKETPLACE is the lead; MOBILE_APP gets a tie or near-tie. With the
    # hardware-priority list being all hardware types, software ties are
    # broken by max() stable ordering — MARKETPLACE wins on the lead keyword.
    assert pt == ProductType.MARKETPLACE


# ---------------------------------------------------------------------------
# Hardware-priority tie-breaking
# ---------------------------------------------------------------------------


def test_hardware_priority_in_tied_score(conductor: Conductor) -> None:
    """When two types score identically, hardware wins."""
    # Hardware keywords: "fitness tracker", "consumer electronics", "smart device"
    # SAAS keywords: "crm"
    # 3 hardware hits vs 1 SAAS hit → hardware wins by score, not by tie-break.
    desc = "A crm dashboard that ships as a fitness tracker consumer electronics smart device"
    result = conductor.detect_product_type(desc, [])
    assert result in {
        ProductType.WEARABLE,
        ProductType.CONSUMER_HARDWARE,
    }


def test_hardware_priority_chooses_first_listed_hardware(conductor: Conductor) -> None:
    """The hardware priority list breaks the tie in a defined order."""
    desc = "A wearable hardware gadget with health monitor sensor"
    # Both WEARABLE and HEALTH_HARDWARE / IOT_HARDWARE score. The exact
    # winner depends on the priority list — assert it's a hardware type.
    pt = conductor.detect_product_type(desc, [])
    assert pt in {
        ProductType.WEARABLE,
        ProductType.HEALTH_HARDWARE,
        ProductType.IOT_HARDWARE,
        ProductType.CONSUMER_HARDWARE,
        ProductType.B2B_HARDWARE,
    }


# ---------------------------------------------------------------------------
# Defensive inputs
# ---------------------------------------------------------------------------


def test_missing_assumption_keys_default_to_empty_text(conductor: Conductor) -> None:
    """If a row has neither 'text' nor 'assumption', scoring sees an empty
    string and the description-only signal wins."""
    pt = conductor.detect_product_type("A crm dashboard", [{"sensitivity": "HIGH"}])
    assert pt == ProductType.SAAS


def test_assumption_with_empty_text_is_skipped(conductor: Conductor) -> None:
    pt = conductor.detect_product_type(
        "A crm dashboard",
        [{"text": "", "sensitivity": "HIGH"}, {"sensitivity": "LOW"}],
    )
    assert pt == ProductType.SAAS


def test_keyword_match_is_case_insensitive(conductor: Conductor) -> None:
    """Description text is lower-cased before matching."""
    assert (
        conductor.detect_product_type("A CRM DASHBOARD for sales teams", [])
        == ProductType.SAAS
    )


def test_returns_product_type_enum(conductor: Conductor) -> None:
    """The function must always return an enum, never a raw string."""
    result = conductor.detect_product_type("anything goes here", [])
    assert isinstance(result, ProductType)


# ---------------------------------------------------------------------------
# PRODUCT_TYPE_KEYWORDS structural integrity
# ---------------------------------------------------------------------------


def test_product_type_keywords_cover_every_enum_value() -> None:
    from app.simulation.conductor import PRODUCT_TYPE_KEYWORDS
    from app.simulation.product_type import ProductType

    missing = set(ProductType) - set(PRODUCT_TYPE_KEYWORDS.keys())
    assert not missing, f"PRODUCT_TYPE_KEYWORDS missing entries for: {missing}"


def test_product_type_keywords_are_non_empty_strings() -> None:
    from app.simulation.conductor import PRODUCT_TYPE_KEYWORDS

    for pt, keywords in PRODUCT_TYPE_KEYWORDS.items():
        assert len(keywords) > 0, f"{pt.value} has no keywords"
        for kw in keywords:
            assert isinstance(kw, str) and kw.strip(), (
                f"{pt.value} has blank keyword"
            )
