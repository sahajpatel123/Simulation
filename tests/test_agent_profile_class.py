"""Tests for the AgentProfile dataclass — tier derivation and serialisation."""
from __future__ import annotations

from app.simulation.profiles import (
    AgentProfile,
    DeviceType,
    IncomeBracket,
    Region,
)


def _profile(region: Region) -> AgentProfile:
    return AgentProfile(
        age=30,
        income_bracket=IncomeBracket.MIDDLE,
        monthly_income=50_000,
        region=region,
        device_type=DeviceType.MOBILE,
        digital_literacy=0.7,
        price_sensitivity=0.5,
        patience_score=0.6,
        motivation=0.7,
        trust_baseline=0.5,
    )


def test_tier_metro_for_metro_region() -> None:
    assert _profile(Region.METRO).tier == "METRO"


def test_tier_tier1_for_cardinal_regions() -> None:
    for region in (Region.NORTH, Region.SOUTH, Region.EAST, Region.WEST):
        assert _profile(region).tier == "TIER1", f"failed for {region}"


def test_tier_tier3_for_central_region() -> None:
    assert _profile(Region.CENTRAL).tier == "TIER3"


def test_tier_tier2_for_tier2_region() -> None:
    assert _profile(Region.TIER2).tier == "TIER2"


def test_tier_tier3_for_tier3_region() -> None:
    assert _profile(Region.TIER3).tier == "TIER3"


def test_to_dict_replaces_enums_with_values() -> None:
    data = _profile(Region.METRO).to_dict()

    assert data["region"] == "METRO"
    assert data["income_bracket"] == "MIDDLE"
    assert data["device_type"] == "MOBILE"
    assert data["tier"] == "METRO"
    assert data["age"] == 30
    assert data["monthly_income"] == 50_000


def test_to_dict_does_not_return_dataclass_instances() -> None:
    data = _profile(Region.TIER3).to_dict()
    assert isinstance(data["region"], str)
    assert isinstance(data["income_bracket"], str)
    assert isinstance(data["device_type"], str)
