"""Tests for small helpers in ``app.simulation.comparison``.

Covers the pure helpers that drive labelling, cluster-rate coercion, and
finding metadata fallbacks.
"""
from __future__ import annotations

from app.simulation.comparison import (
    _cluster_rate,
    _finding_domain,
    _finding_severity,
    _label_for_index,
)


def test_label_for_index_within_alphabet() -> None:
    assert _label_for_index(0) == "A"
    assert _label_for_index(1) == "B"
    assert _label_for_index(25) == "Z"


def test_label_for_index_outside_alphabet_falls_back_to_one_indexed() -> None:
    assert _label_for_index(26) == "27"
    assert _label_for_index(99) == "100"


def test_label_for_index_negative_falls_back_to_one_indexed() -> None:
    assert _label_for_index(-1) == "0"


def test_cluster_rate_with_dict_uses_conversion_rate() -> None:
    assert _cluster_rate({"conversion_rate": 0.12}) == 0.12


def test_cluster_rate_with_dict_uses_conversion_alias() -> None:
    assert _cluster_rate({"conversion": 0.08}) == 0.08


def test_cluster_rate_with_raw_float() -> None:
    assert _cluster_rate(0.05) == 0.05


def test_cluster_rate_clamps_negative_to_zero() -> None:
    assert _cluster_rate(-0.5) == 0.0
    assert _cluster_rate({"conversion_rate": -1.0}) == 0.0


def test_cluster_rate_clamps_above_one() -> None:
    assert _cluster_rate(1.5) == 1.0


def test_cluster_rate_invalid_string_returns_zero() -> None:
    assert _cluster_rate("not a number") == 0.0


def test_finding_domain_prefers_architect_name() -> None:
    assert _finding_domain({"architect_name": "PricingArchitect"}) == "PricingArchitect"


def test_finding_domain_falls_back_to_domain_field() -> None:
    assert _finding_domain({"domain": "Trust"}) == "Trust"


def test_finding_domain_unknown_when_missing() -> None:
    assert _finding_domain({}) == "Unknown"


def test_finding_severity_normalises_case() -> None:
    assert _finding_severity({"severity": "critical"}) == "CRITICAL"


def test_finding_severity_defaults_to_info() -> None:
    assert _finding_severity({}) == "INFO"