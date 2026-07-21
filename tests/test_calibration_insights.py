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
