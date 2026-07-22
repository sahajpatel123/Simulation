"""
Tests for the calibration-status diagnostics helpers and the
``GET /analytics/calibration/status`` endpoint smoke-check
(cycle 31 calibration-status).

These tests focus on the pure helper layer (no DB). The route just threads
SQL rows through the helpers and validates inputs.
"""
from __future__ import annotations

import json
from typing import Any


KNOWN_ARCHITECTS: list[str] = [
    "MarketTimingArchitect",
    "PricingArchitect",
    "OnboardingArchitect",
    "RetentionArchitect",
]


# ---------------------------------------------------------------------------
# build_outcome_coverage
# ---------------------------------------------------------------------------


def test_outcome_coverage_all_zero() -> None:
    from app.simulation.calibration_insights import build_outcome_coverage

    out = build_outcome_coverage(0, 0, 0)
    assert out == {
        "total": 0,
        "validated": 0,
        "rejected": 0,
        "pending": 0,
        "validation_rate_pct": 0.0,
    }


def test_outcome_coverage_basic() -> None:
    from app.simulation.calibration_insights import build_outcome_coverage

    out = build_outcome_coverage(total=100, validated=40, rejected=20)
    # pending = max(0, 100 - 40 - 20) = 40
    assert out["total"] == 100
    assert out["validated"] == 40
    assert out["rejected"] == 20
    assert out["pending"] == 40
    assert out["validation_rate_pct"] == 40.0


def test_outcome_coverage_handles_negative_pending() -> None:
    """If stale counts make validated+rejected > total, floor pending at 0."""
    from app.simulation.calibration_insights import build_outcome_coverage

    out = build_outcome_coverage(total=10, validated=8, rejected=5)
    # Without explicit pending: max(0, 10 - 8 - 5) = 0
    assert out["pending"] == 0


def test_outcome_coverage_explicit_pending_overrides() -> None:
    from app.simulation.calibration_insights import build_outcome_coverage

    out = build_outcome_coverage(total=100, validated=40, rejected=20, pending=50)
    assert out["pending"] == 50


def test_outcome_coverage_handles_none_inputs() -> None:
    from app.simulation.calibration_insights import build_outcome_coverage

    out = build_outcome_coverage(None, None, None)
    assert out["total"] == 0
    assert out["validation_rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# build_architect_health
# ---------------------------------------------------------------------------


def test_architect_health_empty_input_includes_all_known() -> None:
    from app.simulation.calibration_insights import build_architect_health

    out = build_architect_health([], KNOWN_ARCHITECTS)
    # Every known architect appears with empty defaults.
    names = [h["architect_name"] for h in out]
    assert names == sorted(KNOWN_ARCHITECTS)
    for h in out:
        assert h["correction_count"] == 0
        assert h["avg_scalar"] == 1.0
        assert h["max_abs_drift"] == 0.0
        assert h["is_calibrated"] is False


def test_architect_health_aggregates_scalars_and_samples() -> None:
    from app.simulation.calibration_insights import build_architect_health

    corrections = [
        {
            "architect_name": "PricingArchitect",
            "correction_scalar": 1.05,
            "confidence_weight": 0.6,
            "effective_sample_count": 8.0,
        },
        {
            "architect_name": "PricingArchitect",
            "correction_scalar": 0.92,
            "confidence_weight": 0.4,
            "effective_sample_count": 12.0,
        },
        {
            "architect_name": "OnboardingArchitect",
            "correction_scalar": 0.80,
            "confidence_weight": 0.7,
            "effective_sample_count": 5.0,
        },
    ]
    out = build_architect_health(corrections, KNOWN_ARCHITECTS)
    by_name = {h["architect_name"]: h for h in out}

    pricing = by_name["PricingArchitect"]
    assert pricing["correction_count"] == 2
    # avg_scalar = round((1.05 + 0.92) / 2, 4) = 0.985
    assert pricing["avg_scalar"] == 0.985
    assert pricing["max_abs_drift"] == 0.08  # max(|1.05-1|, |0.92-1|)
    assert pricing["confidence_avg"] == 0.5
    assert pricing["effective_sample_count"] == 20.0
    assert pricing["is_calibrated"] is True  # >= 10

    onb = by_name["OnboardingArchitect"]
    assert onb["correction_count"] == 1
    assert onb["effective_sample_count"] == 5.0
    assert onb["is_calibrated"] is False  # 5 < 10


def test_architect_health_unknown_architect_still_appears() -> None:
    from app.simulation.calibration_insights import build_architect_health

    corrections = [
        {
            "architect_name": "MadeUpArchitect",
            "correction_scalar": 0.95,
            "confidence_weight": 0.2,
            "effective_sample_count": 2.0,
        }
    ]
    out = build_architect_health(corrections, KNOWN_ARCHITECTS)
    names = [h["architect_name"] for h in out]
    assert "MadeUpArchitect" in names
    # The result is sorted alphabetically by architect_name. MadeUpArchitect
    # sorts before the known M*/O*/P*/R* names alphabetically.
    assert sorted(names) == names


def test_architect_health_skips_rows_without_name() -> None:
    from app.simulation.calibration_insights import build_architect_health

    corrections: list[dict[str, Any]] = [
        {"architect_name": "", "correction_scalar": 1.0, "effective_sample_count": 5.0},
        {"correction_scalar": 1.0, "effective_sample_count": 5.0},  # missing key
    ]
    out = build_architect_health(corrections, KNOWN_ARCHITECTS)
    # Only the known architects with no corrections appear.
    assert all(h["correction_count"] == 0 for h in out)


# ---------------------------------------------------------------------------
# summarise_calibration
# ---------------------------------------------------------------------------


def test_summarise_calibration_empty() -> None:
    from app.simulation.calibration_insights import summarise_calibration

    out = summarise_calibration([], corrections=None)
    assert out["total_correction_rows"] == 0
    assert out["calibrated_architects"] == 0
    assert out["under_calibrated_architects"] == 0
    assert out["under_calibrated_list"] == []


def test_summarise_calibration_classifies_architects() -> None:
    from app.simulation.calibration_insights import summarise_calibration

    health = [
        {"architect_name": "A", "is_calibrated": True, "effective_sample_count": 25.0},
        {"architect_name": "B", "is_calibrated": False, "effective_sample_count": 5.0},
        {"architect_name": "C", "is_calibrated": True, "effective_sample_count": 12.0},
        {"architect_name": "D", "is_calibrated": False, "effective_sample_count": 8.0},
    ]
    out = summarise_calibration(health, corrections=[{}] * 7)
    assert out["total_correction_rows"] == 7
    assert out["calibrated_architects"] == 2
    assert out["under_calibrated_architects"] == 2
    assert out["under_calibrated_list"] == ["B", "D"]


# ---------------------------------------------------------------------------
# build_product_type_breakdown
# ---------------------------------------------------------------------------


def test_product_type_breakdown_groups_correctly() -> None:
    from app.simulation.calibration_insights import build_product_type_breakdown

    corrections = [
        {"product_type": "saas"},
        {"product_type": "saas"},
        {"product_type": "marketplace"},
        {"product_type": None},
        {"product_type": ""},
    ]
    out = build_product_type_breakdown(corrections)
    # None and "" collapse to "ALL".
    assert out == {"SAAS": 2, "MARKETPLACE": 1, "ALL": 2}


def test_product_type_breakdown_sorts_by_count_desc() -> None:
    from app.simulation.calibration_insights import build_product_type_breakdown

    corrections = [{"product_type": t} for t in ["a", "b", "b", "c", "c", "c"]]
    out = build_product_type_breakdown(corrections)
    keys = list(out.keys())
    assert keys == ["C", "B", "A"]


def test_product_type_breakdown_empty() -> None:
    from app.simulation.calibration_insights import build_product_type_breakdown

    assert build_product_type_breakdown(None) == {}
    assert build_product_type_breakdown([]) == {}


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------


def test_calibration_status_out_serialises_full_payload() -> None:
    from app.schemas.calibration import (
        ArchitectHealth,
        CalibrationStatusOut,
        OutcomeCoverage,
    )

    out = CalibrationStatusOut(
        outcome_coverage=OutcomeCoverage(
            total=100, validated=40, rejected=20, pending=40, validation_rate_pct=40.0
        ),
        total_correction_rows=42,
        by_architect=[
            ArchitectHealth(
                architect_name="PricingArchitect",
                correction_count=3,
                avg_scalar=0.95,
                max_abs_drift=0.08,
                confidence_avg=0.5,
                effective_sample_count=22.0,
                is_calibrated=True,
            )
        ],
        by_product_type={"SAAS": 30, "MARKETPLACE": 12},
        calibrated_architects=1,
        under_calibrated_architects=19,
        under_calibrated_list=["OnboardingArchitect", "RetentionArchitect"],
        generated_at="2026-07-21T20:00:00+00:00",
    )
    dumped = out.model_dump()
    assert dumped["outcome_coverage"]["total"] == 100
    assert dumped["total_correction_rows"] == 42
    assert dumped["by_architect"][0]["architect_name"] == "PricingArchitect"
    assert dumped["under_calibrated_list"] == ["OnboardingArchitect", "RetentionArchitect"]
    # Round-trip via JSON without errors.
    json.dumps(dumped)


def test_calibration_status_out_defaults_when_empty() -> None:
    from app.schemas.calibration import CalibrationStatusOut

    out = CalibrationStatusOut(generated_at="2026-01-01T00:00:00")
    assert out.outcome_coverage.total == 0
    assert out.total_correction_rows == 0
    assert out.by_architect == []
    assert out.by_product_type == {}
    assert out.calibrated_architects == 0


# ---------------------------------------------------------------------------
# Route registration smoke check
# ---------------------------------------------------------------------------


def test_analytics_router_exposes_calibration_status_endpoint() -> None:
    """Source-level check: the new admin route is declared."""
    src_path = "backend/app/api/v1/analytics.py"
    with open(src_path) as fh:
        source = fh.read()
    assert '"/calibration/status"' in source
    assert "def calibration_status(" in source
    assert "response_model=CalibrationStatusOut" in source
    # Admin guard present.
    assert "_require_admin(current_user)" in source
    # Helpers wired in.
    for fn in (
        "build_outcome_coverage",
        "build_architect_health",
        "summarise_calibration",
        "build_product_type_breakdown",
    ):
        assert fn in source, f"analytics.py must call {fn}"


def test_calibration_status_module_is_admin_gated() -> None:
    """The new route must explicitly call _require_admin."""
    src_path = "backend/app/api/v1/analytics.py"
    with open(src_path) as fh:
        source = fh.read()
    # Locate the calibration_status function and verify _require_admin is
    # the first non-decorator statement inside.
    fn_start = source.find("def calibration_status(")
    assert fn_start > 0
    # Slice until the next top-level "def " to keep just the body.
    next_def = source.find("\ndef ", fn_start + 1)
    body = source[fn_start:next_def if next_def > 0 else fn_start + 2000]
    assert "_require_admin(current_user)" in body


# ---------------------------------------------------------------------------
# build_weighted_drift (cycle 32 — weighted-drift analytics)
# ---------------------------------------------------------------------------


def test_weighted_drift_empty_input_yields_zero_state() -> None:
    from app.simulation.calibration_insights import build_weighted_drift

    out = build_weighted_drift(None, known_architect_names=KNOWN_ARCHITECTS)
    assert out["total_architects"] == len(KNOWN_ARCHITECTS)
    assert out["biased_up_count"] == 0
    assert out["biased_down_count"] == 0
    assert out["stable_count"] == len(KNOWN_ARCHITECTS)
    by_arch = {row["architect_name"]: row for row in out["by_architect"]}
    for name in KNOWN_ARCHITECTS:
        assert by_arch[name]["direction"] == "STABLE"
        assert by_arch[name]["weighted_drift"] == 0.0


def test_weighted_drift_downward_bias_with_confidence() -> None:
    """Drift = scalar - 1; weight by confidence. Mean < 1 → BIASED_DOWN."""
    from app.simulation.calibration_insights import build_weighted_drift

    corrections = [
        {
            "architect_name": "PricingArchitect",
            "correction_scalar": 0.9,
            "confidence_weight": 0.8,
            "effective_sample_count": 12.0,
        },
        {
            "architect_name": "PricingArchitect",
            "correction_scalar": 1.0,
            "confidence_weight": 0.2,
            "effective_sample_count": 4.0,
        },
    ]
    out = build_weighted_drift(corrections, known_architect_names=KNOWN_ARCHITECTS)
    row = next(r for r in out["by_architect"] if r["architect_name"] == "PricingArchitect")
    # (-0.1 * 0.8) + (0.0 * 0.2) = -0.08
    assert row["weighted_drift"] == -0.08
    assert row["confidence_sum"] == 1.0
    assert row["sample_sum"] == 16.0
    assert row["direction"] == "BIASED_DOWN"


def test_weighted_drift_upward_bias_with_confidence() -> None:
    from app.simulation.calibration_insights import build_weighted_drift

    corrections = [
        {
            "architect_name": "OnboardingArchitect",
            "correction_scalar": 1.2,
            "confidence_weight": 0.5,
            "effective_sample_count": 8.0,
        }
    ]
    out = build_weighted_drift(corrections, known_architect_names=KNOWN_ARCHITECTS)
    row = next(
        r for r in out["by_architect"] if r["architect_name"] == "OnboardingArchitect"
    )
    # (0.2 * 0.5) = +0.1
    assert row["weighted_drift"] == 0.1
    assert row["direction"] == "BIASED_UP"


def test_weighted_drift_stable_when_corrections_average_to_one() -> None:
    """Conflicting drifts cancel → STABLE (within 1e-6)."""
    from app.simulation.calibration_insights import build_weighted_drift

    corrections = [
        {
            "architect_name": "RetentionArchitect",
            "correction_scalar": 0.95,
            "confidence_weight": 0.4,
            "effective_sample_count": 5.0,
        },
        {
            "architect_name": "RetentionArchitect",
            "correction_scalar": 1.05,
            "confidence_weight": 0.4,
            "effective_sample_count": 5.0,
        },
    ]
    out = build_weighted_drift(corrections, known_architect_names=KNOWN_ARCHITECTS)
    row = next(
        r for r in out["by_architect"] if r["architect_name"] == "RetentionArchitect"
    )
    # (-0.05 * 0.4) + (0.05 * 0.4) = 0
    assert row["weighted_drift"] == 0.0
    assert row["direction"] == "STABLE"


def test_weighted_drift_handles_garbage_inputs_safely() -> None:
    """Bad scalars / missing fields default to neutral values."""
    from app.simulation.calibration_insights import build_weighted_drift

    corrections: list[dict[str, Any]] = [
        {
            "architect_name": "MarketTimingArchitect",
            "correction_scalar": "not-a-number",
            "confidence_weight": None,
            "effective_sample_count": "twelve",
        },
        {
            # row with no architect_name -> ignored entirely
            "correction_scalar": 0.5,
            "confidence_weight": 0.9,
            "effective_sample_count": 3.0,
        },
    ]
    out = build_weighted_drift(corrections, known_architect_names=KNOWN_ARCHITECTS)
    row = next(
        r for r in out["by_architect"] if r["architect_name"] == "MarketTimingArchitect"
    )
    # scalar falls back to 1.0 → drift 0 → STABLE
    assert row["direction"] == "STABLE"
    assert row["confidence_sum"] == 0.0
    assert row["sample_sum"] == 0.0


def test_weighted_drift_direction_counts_aggregate_correctly() -> None:
    from app.simulation.calibration_insights import build_weighted_drift

    corrections = [
        {
            "architect_name": "PricingArchitect",
            "correction_scalar": 0.8,
            "confidence_weight": 0.6,
            "effective_sample_count": 2.0,
        },  # BIASED_DOWN
        {
            "architect_name": "OnboardingArchitect",
            "correction_scalar": 1.3,
            "confidence_weight": 0.4,
            "effective_sample_count": 2.0,
        },  # BIASED_UP
        {
            "architect_name": "RetentionArchitect",
            "correction_scalar": 1.0,
            "confidence_weight": 1.0,
            "effective_sample_count": 1.0,
        },  # STABLE
    ]
    out = build_weighted_drift(corrections, known_architect_names=KNOWN_ARCHITECTS)
    assert out["biased_up_count"] == 1
    assert out["biased_down_count"] == 1
    assert out["stable_count"] == len(KNOWN_ARCHITECTS) - 2


def test_weighted_drift_known_architects_always_present() -> None:
    """Known architects with no rows surface as STABLE zeros."""
    from app.simulation.calibration_insights import build_weighted_drift

    out = build_weighted_drift([], known_architect_names=KNOWN_ARCHITECTS)
    names = [r["architect_name"] for r in out["by_architect"]]
    assert sorted(names) == sorted(KNOWN_ARCHITECTS)


def test_weighted_drift_schema_round_trip() -> None:
    from app.schemas.calibration import (
        ArchitectWeightedDrift,
        CalibrationStatusOut,
        WeightedDriftSummary,
    )

    drift_summary = WeightedDriftSummary(
        total_architects=2,
        biased_up_count=1,
        biased_down_count=1,
        stable_count=0,
        by_architect=[
            ArchitectWeightedDrift(
                architect_name="PricingArchitect",
                weighted_drift=-0.05,
                confidence_sum=0.6,
                sample_sum=12.0,
                direction="BIASED_DOWN",
            ),
            ArchitectWeightedDrift(
                architect_name="RetentionArchitect",
                weighted_drift=0.03,
                confidence_sum=0.4,
                sample_sum=8.0,
                direction="BIASED_UP",
            ),
        ],
    )
    out = CalibrationStatusOut(
        weighted_drift=drift_summary,
        generated_at="2026-07-23T00:00:00+00:00",
    )
    dumped = out.model_dump()
    assert dumped["weighted_drift"]["total_architects"] == 2
    assert dumped["weighted_drift"]["by_architect"][0]["direction"] == "BIASED_DOWN"
    json.dumps(dumped)


def test_weighted_drift_schema_defaults_when_empty() -> None:
    from app.schemas.calibration import WeightedDriftSummary

    summary = WeightedDriftSummary()
    assert summary.total_architects == 0
    assert summary.biased_up_count == 0
    assert summary.biased_down_count == 0
    assert summary.stable_count == 0
    assert summary.by_architect == []


def test_calibration_status_out_round_trip_includes_weighted_drift() -> None:
    """End-to-end schema coverage: weighted_drift defaults carry through."""
    from app.schemas.calibration import CalibrationStatusOut

    out = CalibrationStatusOut(generated_at="2026-07-23T00:00:00+00:00")
    assert out.weighted_drift.total_architects == 0
    dumped = out.model_dump()
    assert "weighted_drift" in dumped
    assert dumped["weighted_drift"]["biased_up_count"] == 0


def test_analytics_router_wires_weighted_drift_into_calibration_status() -> None:
    """Source-level check: the calibration route now exposes weighted drift."""
    src_path = "backend/app/api/v1/analytics.py"
    with open(src_path) as fh:
        source = fh.read()
    assert "build_weighted_drift" in source
    assert "weighted_drift=drift_summary" in source
    # The new schemas are imported.
    assert "ArchitectWeightedDrift" in source
    assert "WeightedDriftSummary" in source
