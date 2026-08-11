"""Pure tests for the learned-correction application helpers.

The calibration engine writes ``architect_corrections`` rows and the
Conductor now loads and applies them. These tests pin the pure selection
and scaling logic: product-type filtering, confidence gating, sanitised
scalars, deterministic tie-breaking, and the guarantee that only
probability/score floats in ``[0.0, 1.0]`` are adjusted.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput
from app.simulation.correction_application import (
    MAX_CORRECTION_SCALAR,
    MIN_CORRECTION_SCALAR,
    Correction,
    apply_correction_to_output,
    best_correction_for_architect_cluster,
    correction_for_output,
    index_corrections,
)


def _row(**overrides: object) -> dict:
    base: dict = {
        "architect_name": "PricingArchitect",
        "product_type": "saas",
        "product_attribute": "ALL",
        "cluster_id": "ALL",
        "correction_scalar": 0.9,
        "confidence_weight": 0.8,
        "effective_sample_count": 25.0,
        "scope": "CATEGORY_GLOBAL",
    }
    base.update(overrides)
    return base


def _output(
    *,
    architect_name: str = "PricingArchitect",
    cluster_id: str = "metro_power_professional",
    metrics: dict | None = None,
) -> ArchitectOutput:
    return ArchitectOutput(
        architect_name=architect_name,
        cluster_id=cluster_id,
        metrics=metrics
        or {
            "will_pay_probability": 0.8,
            "price_ceiling": 499.0,
            "steps_to_purchase": 3,
            "is_expensive": False,
        },
        flags={},
        narrative_findings=[],
        severity="INFO",
    )


# ── index_corrections ─────────────────────────────────────────────────────


def test_index_filters_to_product_type() -> None:
    rows = [
        _row(product_type="saas", cluster_id="c1", correction_scalar=0.9),
        _row(product_type="marketplace", cluster_id="c1", correction_scalar=1.1),
    ]
    indexed = index_corrections(rows, "saas")

    assert list(indexed.keys()) == [("PricingArchitect", "c1")]
    assert indexed[("PricingArchitect", "c1")].correction_scalar == 0.9


def test_index_ignores_low_confidence_rows() -> None:
    rows = [
        _row(cluster_id="c1", confidence_weight=0.19),
        _row(cluster_id="c2", confidence_weight=0.2),
    ]
    indexed = index_corrections(rows, "saas")

    assert list(indexed.keys()) == [("PricingArchitect", "c2")]


def test_index_ignores_malformed_rows() -> None:
    rows = [
        _row(cluster_id="c1", correction_scalar=float("nan")),
        _row(cluster_id="c2", correction_scalar="not-a-number"),
        _row(cluster_id="c3", confidence_weight=None),
        _row(cluster_id="c4", architect_name=None),
        {"product_type": "saas", "cluster_id": "c5"},  # missing everything else
    ]

    assert index_corrections(rows, "saas") == {}


def test_index_picks_highest_confidence() -> None:
    rows = [
        _row(cluster_id="c1", correction_scalar=0.9, confidence_weight=0.5),
        _row(cluster_id="c1", correction_scalar=1.05, confidence_weight=0.9),
    ]
    indexed = index_corrections(rows, "saas")

    assert indexed[("PricingArchitect", "c1")].correction_scalar == 1.05


def test_index_prefers_cluster_specific_on_confidence_tie() -> None:
    rows = [
        _row(cluster_id="ALL", correction_scalar=0.9, confidence_weight=0.8),
        _row(cluster_id="c1", correction_scalar=1.1, confidence_weight=0.8),
    ]
    indexed = index_corrections(rows, "saas")

    correction = indexed[("PricingArchitect", "c1")]
    assert correction.cluster_id == "c1"
    assert correction.correction_scalar == 1.1


def test_index_uses_sample_count_to_break_ties() -> None:
    rows = [
        _row(cluster_id="c1", correction_scalar=0.9, effective_sample_count=10.0),
        _row(cluster_id="c1", correction_scalar=1.0, effective_sample_count=40.0),
    ]
    indexed = index_corrections(rows, "saas")

    assert indexed[("PricingArchitect", "c1")].correction_scalar == 1.0


def test_index_clamps_out_of_range_scalars() -> None:
    rows = [
        _row(cluster_id="c1", correction_scalar=0.01),
        _row(cluster_id="c2", correction_scalar=9.0),
    ]
    indexed = index_corrections(rows, "saas")

    assert indexed[("PricingArchitect", "c1")].correction_scalar == MIN_CORRECTION_SCALAR
    assert indexed[("PricingArchitect", "c2")].correction_scalar == MAX_CORRECTION_SCALAR


# ── correction_for_output / apply_correction_to_output ────────────────────


def test_correction_for_output_matches_architect_and_cluster() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.9,
            confidence_weight=0.8,
        )
    }

    assert correction_for_output(_output(), corrections) is not None
    assert correction_for_output(
        _output(cluster_id="tier3_first_time_app_user"), corrections
    ) is None
    assert correction_for_output(_output(), None) is None
    assert correction_for_output(_output(), {}) is None


def test_correction_for_output_falls_back_to_global_all() -> None:
    corrections = {
        ("PricingArchitect", "ALL"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="ALL",
            correction_scalar=0.9,
            confidence_weight=0.8,
        )
    }

    assert correction_for_output(_output(), corrections) is not None
    assert (
        correction_for_output(_output(), corrections).correction_scalar
        == 0.9
    )


def test_correction_for_output_prefers_higher_confidence_between_exact_and_all() -> None:
    corrections = {
        ("PricingArchitect", "ALL"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="ALL",
            correction_scalar=0.95,
            confidence_weight=0.9,
        ),
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.6,
            confidence_weight=0.5,
        ),
    }

    assert (
        correction_for_output(_output(), corrections).correction_scalar
        == 0.95
    )


def test_correction_for_output_prefers_exact_on_confidence_tie() -> None:
    corrections = {
        ("PricingArchitect", "ALL"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="ALL",
            correction_scalar=0.9,
            confidence_weight=0.8,
        ),
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.7,
            confidence_weight=0.8,
        ),
    }

    assert (
        correction_for_output(_output(), corrections).correction_scalar
        == 0.7
    )


def test_best_correction_works_without_an_output_object() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.9,
            confidence_weight=0.8,
        )
    }

    selected = best_correction_for_architect_cluster(
        "PricingArchitect",
        "metro_power_professional",
        corrections,
    )

    assert selected is not None
    assert selected.correction_scalar == 0.9
    assert (
        best_correction_for_architect_cluster(
            "PricingArchitect",
            "tier3_first_time_app_user",
            corrections,
        )
        is None
    )
    assert (
        best_correction_for_architect_cluster(
            "PricingArchitect",
            "metro_power_professional",
            {},
        )
        is None
    )


def test_best_correction_matches_output_selection_for_global_fallback() -> None:
    corrections = {
        ("PricingArchitect", "ALL"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="ALL",
            correction_scalar=0.95,
            confidence_weight=0.9,
        ),
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.6,
            confidence_weight=0.5,
        ),
    }

    from_output = correction_for_output(_output(), corrections)
    from_parts = best_correction_for_architect_cluster(
        "PricingArchitect",
        "metro_power_professional",
        corrections,
    )

    assert from_output is from_parts
    assert from_parts.correction_scalar == 0.95


def test_apply_scales_only_probability_floats() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.5,
            confidence_weight=0.8,
        )
    }

    corrected = apply_correction_to_output(_output(), corrections)

    assert corrected.metrics["will_pay_probability"] == 0.4
    # Unbounded / non-probability values must pass through untouched.
    assert corrected.metrics["price_ceiling"] == 499.0
    assert corrected.metrics["steps_to_purchase"] == 3
    assert corrected.metrics["is_expensive"] is False


def test_apply_uses_global_all_correction_fallback() -> None:
    corrections = {
        ("PricingArchitect", "ALL"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="ALL",
            correction_scalar=0.5,
            confidence_weight=0.8,
        )
    }

    corrected = apply_correction_to_output(_output(), corrections)

    assert corrected.metrics["will_pay_probability"] == 0.4


def test_apply_clamps_results_to_unit_interval() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=2.0,
            confidence_weight=0.8,
        )
    }
    output = _output(metrics={"will_pay_probability": 1.0})

    assert apply_correction_to_output(output, corrections).metrics[
        "will_pay_probability"
    ] == 1.0


def test_apply_neutral_scalar_is_a_no_op() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=1.0,
            confidence_weight=0.8,
        )
    }
    output = _output()

    assert apply_correction_to_output(output, corrections) is output


def test_apply_returns_same_object_without_match_or_change() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=1.5,
            confidence_weight=0.8,
        )
    }
    # No matching correction.
    unmatched = _output(cluster_id="other_cluster")
    assert apply_correction_to_output(unmatched, corrections) is unmatched
    # Matching correction but no eligible metric.
    only_ints = _output(metrics={"steps_to_purchase": 3, "price_ceiling": 499.0})
    assert apply_correction_to_output(only_ints, corrections) is only_ints


def test_apply_does_not_mutate_original_output() -> None:
    corrections = {
        ("PricingArchitect", "metro_power_professional"): Correction(
            architect_name="PricingArchitect",
            product_type="saas",
            product_attribute="ALL",
            cluster_id="metro_power_professional",
            correction_scalar=0.5,
            confidence_weight=0.8,
        )
    }
    original = _output()

    corrected = apply_correction_to_output(original, corrections)

    assert corrected is not original
    assert original.metrics["will_pay_probability"] == 0.8
