"""Tests for the architect-stack registry endpoint.

Covers the pure helper (full registry, product-type filter, coverage and
missing-entry accounting) plus the API contract (typed response, invalid
product-type handling) without touching the DB.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.schemas.architect_stack import ArchitectStackRegistryOut
from app.simulation.architect_stack import build_architect_stack_registry
from app.simulation.product_type import ProductType

# Importing ``app.api.v1.simulations`` pulls in the whole API router, which
# imports the billing router and the real ``razorpay`` SDK. On Python 3.14
# the installed SDK fails on ``pkg_resources``; the route tests only need
# the module's names, so stub the SDK the same way the other route tests do.
if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub


class _Architect:
    def __init__(self, name: str, product_types: list[str] | None = None) -> None:
        self._name = name
        self._product_types = list(product_types or [])

    @property
    def name(self) -> str:
        return self._name

    @property
    def product_types(self) -> list[str]:
        return list(self._product_types)


_REGISTRY: dict[str, _Architect] = {
    "UniversalArchitect": _Architect("UniversalArchitect", []),
    "SpecializedArchitect": _Architect(
        "SpecializedArchitect", ["saas", "marketplace"]
    ),
    "HardwareArchitect": _Architect(
        "HardwareArchitect", ["consumer_hardware"]
    ),
}

_STACKS: dict[str, list[str]] = {
    "saas": ["UniversalArchitect", "SpecializedArchitect"],
    "marketplace": ["UniversalArchitect", "SpecializedArchitect"],
    "consumer_hardware": ["UniversalArchitect", "HardwareArchitect"],
}

_ALL_PRODUCT_TYPES = ["saas", "marketplace", "consumer_hardware"]


def _build(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "registry": _REGISTRY,
        "stacks": _STACKS,
        "all_product_types": _ALL_PRODUCT_TYPES,
    }
    defaults.update(kwargs)
    return build_architect_stack_registry(**defaults)


# ── Pure helper ─────────────────────────────────────────────────────────


def test_full_registry_reports_activation_and_coverage() -> None:
    payload = _build()

    assert payload["product_type"] is None
    assert payload["total_architects"] == 3
    assert payload["stack_size"] is None
    assert payload["universal_count"] == 1
    assert payload["specialized_count"] == 2

    by_name = {row["name"]: row for row in payload["architects"]}
    assert by_name["UniversalArchitect"]["universal"] is True
    assert by_name["UniversalArchitect"]["stack_count"] == 3
    assert by_name["UniversalArchitect"]["stacked_product_types"] == [
        "consumer_hardware",
        "marketplace",
        "saas",
    ]
    assert by_name["SpecializedArchitect"]["universal"] is False
    assert by_name["SpecializedArchitect"]["stack_count"] == 2
    assert by_name["HardwareArchitect"]["stack_count"] == 1

    coverage = {row["product_type"]: row for row in payload["product_coverage"]}
    assert coverage["saas"]["stack_size"] == 2
    assert coverage["saas"]["universal_count"] == 1
    assert coverage["saas"]["specialized_count"] == 1
    assert coverage["consumer_hardware"]["universal_count"] == 1
    assert coverage["consumer_hardware"]["specialized_count"] == 1


def test_filter_returns_active_stack_first_then_inactive() -> None:
    payload = _build(product_type="SAAS")

    assert payload["product_type"] == "saas"
    assert payload["stack_size"] == 2
    assert payload["universal_count"] == 1
    assert payload["specialized_count"] == 1

    names = [row["name"] for row in payload["architects"]]
    assert names[:2] == ["UniversalArchitect", "SpecializedArchitect"]
    assert names[2:] == ["HardwareArchitect"]

    active = {
        row["name"]: row
        for row in payload["architects"]
        if row["active_for_product_type"]
    }
    assert active["UniversalArchitect"]["stack_position"] == 1
    assert active["SpecializedArchitect"]["stack_position"] == 2
    inactive = next(
        row
        for row in payload["architects"]
        if row["name"] == "HardwareArchitect"
    )
    assert inactive["active_for_product_type"] is False
    assert inactive["stack_position"] is None


def test_unknown_product_type_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown product_type"):
        _build(product_type="quantum")


def test_missing_stack_entry_is_counted_without_crashing() -> None:
    stacks = {
        "saas": ["UniversalArchitect", "GhostArchitect"],
        "marketplace": ["UniversalArchitect"],
        "consumer_hardware": ["UniversalArchitect", "HardwareArchitect"],
    }
    payload = _build(stacks=stacks)

    coverage = {row["product_type"]: row for row in payload["product_coverage"]}
    assert coverage["saas"]["stack_size"] == 2
    assert coverage["saas"]["missing_count"] == 1
    assert coverage["saas"]["universal_count"] == 1
    assert payload["total_architects"] == 3


def test_filter_counts_stay_consistent_with_missing_stack_entry() -> None:
    stacks = {
        "saas": [
            "UniversalArchitect",
            "GhostArchitect",
            "SpecializedArchitect",
        ],
        "marketplace": ["UniversalArchitect", "SpecializedArchitect"],
        "consumer_hardware": ["UniversalArchitect", "HardwareArchitect"],
    }
    payload = _build(stacks=stacks, product_type="saas")

    assert payload["stack_size"] == 3
    assert payload["universal_count"] == 1
    assert payload["specialized_count"] == 1
    assert payload["missing_count"] == 1
    assert payload["stack_size"] == (
        payload["universal_count"]
        + payload["specialized_count"]
        + payload["missing_count"]
    )

    coverage = {row["product_type"]: row for row in payload["product_coverage"]}
    assert coverage["saas"]["missing_count"] == 1

    # Active entries keep declared evaluation order and positions, so the
    # ghost between the two real architects is visible in the gap.
    active = [
        row for row in payload["architects"] if row["active_for_product_type"]
    ]
    assert [row["name"] for row in active] == [
        "UniversalArchitect",
        "SpecializedArchitect",
    ]
    assert [row["stack_position"] for row in active] == [1, 3]


def test_full_registry_missing_count_sums_stack_gaps() -> None:
    stacks = {
        "saas": ["UniversalArchitect", "GhostA"],
        "marketplace": ["UniversalArchitect", "GhostA"],
        "consumer_hardware": [
            "UniversalArchitect",
            "HardwareArchitect",
            "GhostB",
        ],
    }
    payload = _build(stacks=stacks)

    assert payload["missing_count"] == 3
    coverage = {row["product_type"]: row for row in payload["product_coverage"]}
    assert sum(row["missing_count"] for row in coverage.values()) == 3


def test_enum_keyed_stacks_resolve_with_string_product_type() -> None:
    stacks = {
        ProductType.SAAS: ["UniversalArchitect", "SpecializedArchitect"],
        ProductType.MARKETPLACE: ["UniversalArchitect", "SpecializedArchitect"],
        ProductType.CONSUMER_HARDWARE: ["UniversalArchitect", "HardwareArchitect"],
    }
    payload = _build(
        stacks=stacks,
        all_product_types=list(ProductType),
        product_type="saas",
    )

    assert payload["product_type"] == "saas"
    assert payload["stack_size"] == 2
    assert payload["missing_count"] == 0
    active = [
        row for row in payload["architects"] if row["active_for_product_type"]
    ]
    assert [row["name"] for row in active] == [
        "UniversalArchitect",
        "SpecializedArchitect",
    ]

    unfiltered = _build(stacks=stacks, all_product_types=list(ProductType))
    by_name = {row["name"]: row for row in unfiltered["architects"]}
    assert by_name["HardwareArchitect"]["stacked_product_types"] == [
        "consumer_hardware"
    ]


def test_registry_key_divergence_uses_architect_name() -> None:
    class NamedArchitect(_Architect):
        pass

    registry = {"SomeRegistryKey": NamedArchitect("CanonicalName", [])}
    stacks = {
        "saas": ["CanonicalName"],
        "marketplace": [],
        "consumer_hardware": [],
    }
    payload = _build(registry=registry, stacks=stacks, product_type="saas")

    assert payload["total_architects"] == 1
    assert payload["architects"][0]["name"] == "CanonicalName"
    assert payload["architects"][0]["active_for_product_type"] is True
    assert payload["architects"][0]["stack_position"] == 1
    assert payload["missing_count"] == 0


def test_generated_at_is_echoed() -> None:
    pinned = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    payload = _build(generated_at=pinned)
    assert payload["generated_at"] == pinned


# ── API contract ────────────────────────────────────────────────────────


def test_route_returns_typed_registry(monkeypatch: Any) -> None:
    import app.api.v1.simulations as sim_mod

    monkeypatch.setattr(sim_mod, "_architect_registry", _REGISTRY)
    monkeypatch.setattr(sim_mod, "ARCHITECT_STACKS", _STACKS)

    out = sim_mod.get_architect_stack(
        product_type="consumer_hardware",
        current_user=types.SimpleNamespace(id=7),
    )

    assert isinstance(out, ArchitectStackRegistryOut)
    assert out.product_type == "consumer_hardware"
    assert out.stack_size == 2
    assert len(out.architects) == 3
    assert out.missing_count == 0
    assert out.product_coverage[0].product_type == "saas"
    assert out.architects[0].name == "UniversalArchitect"
    assert out.architects[0].stack_position == 1


def test_route_rejects_unknown_product_type(monkeypatch: Any) -> None:
    import app.api.v1.simulations as sim_mod

    monkeypatch.setattr(sim_mod, "_architect_registry", _REGISTRY)
    monkeypatch.setattr(sim_mod, "ARCHITECT_STACKS", _STACKS)

    with pytest.raises(HTTPException) as exc_info:
        sim_mod.get_architect_stack(
            product_type="quantum",
            current_user=types.SimpleNamespace(id=7),
        )
    assert exc_info.value.status_code == 400
    assert "Unknown product_type" in exc_info.value.detail
