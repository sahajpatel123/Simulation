"""Tests for the shared ProductType enum."""
from __future__ import annotations

from app.simulation.product_type import ProductType


def test_product_type_has_ten_members() -> None:
    assert len(ProductType) == 15


def test_product_type_string_values() -> None:
    assert ProductType.SAAS.value == "saas"
    assert ProductType.MARKETPLACE.value == "marketplace"
    assert ProductType.MOBILE_APP.value == "mobile_app"
    assert ProductType.DEVELOPER_TOOL.value == "developer_tool"
    assert ProductType.ENTERPRISE_SOFTWARE.value == "enterprise_software"
    assert ProductType.CONSUMER_HARDWARE.value == "consumer_hardware"
    assert ProductType.HEALTH_HARDWARE.value == "health_hardware"
    assert ProductType.IOT_HARDWARE.value == "iot_hardware"
    assert ProductType.WEARABLE.value == "wearable"
    assert ProductType.B2B_HARDWARE.value == "b2b_hardware"


def test_product_type_is_str_subclass() -> None:
    # str mixin means values compare equal to raw strings.
    assert ProductType.SAAS == "saas"
    assert ProductType.WEARABLE == "wearable"


def test_product_type_membership() -> None:
    assert "wearable" in {pt.value for pt in ProductType}
    assert "spaceship" not in {pt.value for pt in ProductType}


def test_product_type_lookup_from_value() -> None:
    assert ProductType("iot_hardware") is ProductType.IOT_HARDWARE


def test_product_type_unknown_value_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        ProductType("robot")