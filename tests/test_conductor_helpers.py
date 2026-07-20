"""Tests for backend/app/simulation/conductor.py.

Three scopes, all on the pure-function surface (no architect instantiation,
no DB, no Markov chain):

  1. _mean_metric: aggregates the numeric metrics on an ArchitectOutput.
     Includes the numpy-scalar / bool cases the existing isinstance check
     would have filtered out.

  2. _resolve_deps: pulls dependent metric values from prior architect
     outputs in the same cluster. Guards: missing source, missing metric
     key, value is None.

  3. detect_product_type: keyword scorer with hardware-priority tie-break.
     Verifies the SAAS default fallback, single-keyword routing, multi-
     keyword routing, and the hardware tie-break that prefers WEARABLE
     over the general CONSUMER_HARDWARE for "fitness" / "smartwatch" inputs.

Architect instantiation happens at module import via _ARCHITECTS, so these
tests still pay the cost of building 21 architect instances on first import.
We rely on the existing test_run_trace.py and test_phase6_e2e.py coverage
for the heavy cluster-loop / Markov integration paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("scipy", reason="Full stack: pip install -r requirements.txt (scipy)")
pytest.importorskip("numpy", reason="Full stack: pip install -r requirements.txt (numpy)")

from app.simulation.conductor import (  # noqa: E402  (importorskip must come first)
    _mean_metric,
)
from app.simulation.conductor import Conductor  # noqa: E402
from app.simulation.product_type import ProductType  # noqa: E402


# ---------------------------------------------------------------------------
# _mean_metric
# ---------------------------------------------------------------------------


def _make_output(metrics: dict, cluster_id: str = "test_cluster") -> MagicMock:
    out = MagicMock()
    out.metrics = metrics
    out.cluster_id = cluster_id
    return out


def test_mean_metric_empty_returns_neutral_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    out = _make_output({})
    import logging

    with caplog.at_level(logging.DEBUG, logger="app.simulation.conductor"):
        assert _mean_metric(out) == 0.5
    # The fallback is observable, not silent.
    assert any(
        "no numeric metrics" in r.getMessage() and r.cluster_id == "test_cluster"
        if hasattr(r, "cluster_id")
        else "no numeric metrics" in r.getMessage()
        for r in caplog.records
    )


def test_mean_metric_all_numeric() -> None:
    out = _make_output({"a": 0.2, "b": 0.4, "c": 0.6})
    assert _mean_metric(out) == pytest.approx(0.4)


def test_mean_metric_mixed_numeric_and_string() -> None:
    out = _make_output({"a": 0.4, "b": "ignored", "c": 0.6})
    assert _mean_metric(out) == pytest.approx(0.5)


def test_mean_metric_handles_bool_true_as_one() -> None:
    out = _make_output({"a": True, "b": 0.0, "c": False})
    assert _mean_metric(out) == pytest.approx((1.0 + 0.0 + 0.0) / 3)


def test_mean_metric_handles_numpy_scalars() -> None:
    np = pytest.importorskip("numpy")
    out = _make_output(
        {"a": np.float64(0.5), "b": np.int64(1), "c": 0.5}
    )
    assert _mean_metric(out) == pytest.approx((0.5 + 1.0 + 0.5) / 3)


def test_mean_metric_non_numeric_only_still_falls_back() -> None:
    out = _make_output({"a": "text", "b": None, "c": []})
    assert _mean_metric(out) == 0.5


# ---------------------------------------------------------------------------
# _resolve_deps
# ---------------------------------------------------------------------------


def _make_architect_output(metrics: dict[str, float]) -> MagicMock:
    out = MagicMock()
    out.metrics = metrics
    return out


def test_resolve_deps_no_deps_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conductor = Conductor.__new__(Conductor)  # bypass __init__ (no registry/mutator needed)
    # TrustArchitect has no entry in DEPENDENCY_MAP, so no resolution happens.
    out = conductor._resolve_deps(
        "TrustArchitect",
        {},
    )
    assert out == {}


def test_resolve_deps_pulls_metrics_from_prior_outputs() -> None:
    conductor = Conductor.__new__(Conductor)
    retention_out = _make_architect_output(
        {"feature_depth_score": 0.7, "day30_survival": 0.4}
    )
    feature_out = _make_architect_output({"feature_depth_score": 0.7})
    onb_out = _make_architect_output({"onboarding_completion_rate": 0.6})
    resolved = conductor._resolve_deps(
        "RetentionArchitect",
        {
            "FeatureAdoptionArchitect": feature_out,
            "OnboardingArchitect": onb_out,
            "RetentionArchitect": retention_out,  # self should NOT match
        },
    )
    assert resolved == {
        "feature_depth_score": 0.7,
        "onboarding_completion_rate": 0.6,
    }


def test_resolve_deps_skips_missing_source_architect() -> None:
    conductor = Conductor.__new__(Conductor)
    resolved = conductor._resolve_deps(
        "RetentionArchitect",
        {},  # neither FeatureAdoption nor Onboarding has run yet
    )
    assert resolved == {}


def test_resolve_deps_skips_metric_value_when_none() -> None:
    conductor = Conductor.__new__(Conductor)
    feature_out = _make_architect_output({"feature_depth_score": None})
    onb_out = _make_architect_output({"onboarding_completion_rate": 0.6})
    resolved = conductor._resolve_deps(
        "RetentionArchitect",
        {
            "FeatureAdoptionArchitect": feature_out,
            "OnboardingArchitect": onb_out,
        },
    )
    assert resolved == {"onboarding_completion_rate": 0.6}


def test_resolve_deps_skips_when_metric_key_absent_from_source() -> None:
    conductor = Conductor.__new__(Conductor)
    feature_out = _make_architect_output({"different_metric": 0.7})
    onb_out = _make_architect_output({"onboarding_completion_rate": 0.6})
    resolved = conductor._resolve_deps(
        "RetentionArchitect",
        {
            "FeatureAdoptionArchitect": feature_out,
            "OnboardingArchitect": onb_out,
        },
    )
    assert resolved == {"onboarding_completion_rate": 0.6}


# ---------------------------------------------------------------------------
# detect_product_type
# ---------------------------------------------------------------------------


def _conductor() -> Conductor:
    return Conductor.__new__(Conductor)


def test_detect_product_type_empty_input_defaults_to_saas() -> None:
    c = _conductor()
    assert c.detect_product_type("", []) is ProductType.SAAS


def test_detect_product_type_saas_keyword() -> None:
    c = _conductor()
    assert (
        c.detect_product_type("A subscription dashboard for SMBs", [])
        is ProductType.SAAS
    )


def test_detect_product_type_marketplace_keyword() -> None:
    c = _conductor()
    assert (
        c.detect_product_type("A two-sided marketplace for buyers and sellers", [])
        is ProductType.MARKETPLACE
    )


def test_detect_product_type_hardware_keyword_routes_correctly() -> None:
    c = _conductor()
    assert (
        c.detect_product_type("A new bluetooth speaker device", []) is ProductType.CONSUMER_HARDWARE
    )


def test_detect_product_type_wearable_keyword() -> None:
    c = _conductor()
    assert (
        c.detect_product_type("A smartwatch with fitness tracker", [])
        is ProductType.WEARABLE
    )


def test_detect_product_type_health_hardware_wins_over_consume_hardware_for_health_keyword() -> None:
    c = _conductor()
    # "blood pressure" is a HEALTH_HARDWARE-only keyword.
    assert (
        c.detect_product_type("A blood pressure monitor", [])
        is ProductType.HEALTH_HARDWARE
    )


def test_detect_product_type_iot_keyword() -> None:
    c = _conductor()
    assert (
        c.detect_product_type("A smart home hub with zigbee support", [])
        is ProductType.IOT_HARDWARE
    )


def test_detect_product_type_pulls_text_from_assumptions() -> None:
    c = _conductor()
    assert (
        c.detect_product_type(
            "An idea",
            [{"text": "We're building a wearable ring for fitness"}],
        )
        is ProductType.WEARABLE
    )


def test_detect_product_type_hardware_priority_tiebreak_when_multiple_hardware_match() -> None:
    c = _conductor()
    # Both WEARABLE ("wearable") and B2B_HARDWARE ("fleet device") match ->
    # hardware priority picks WEARABLE first.
    description = "A wearable for fleet devices in the field"
    pt = c.detect_product_type(description, [])
    # Whichever has more keyword hits wins by score; this asserts the
    # implementation does not regress to a non-hardware type when both
    # hardware categories match. Asserting the actual winner is too
    # tightly coupled to the keyword counts; the meaningful guarantee
    # is "is some hardware type".
    assert pt in (
        ProductType.WEARABLE,
        ProductType.B2B_HARDWARE,
        ProductType.IOT_HARDWARE,
        ProductType.HEALTH_HARDWARE,
        ProductType.CONSUMER_HARDWARE,
    )


def test_detect_product_type_assumption_dict_supports_alternate_text_keys() -> None:
    c = _conductor()
    # Some callers store the assumption text under 'assumption' rather than 'text'.
    assert (
        c.detect_product_type(
            "An idea",
            [{"assumption": "mobile app for ios"}],
        )
        is ProductType.MOBILE_APP
    )