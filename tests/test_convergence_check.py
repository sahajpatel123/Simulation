"""Tests for the per-project convergence check helper +
schema + route registration.

The helper is pure-Python so it can be exercised without
a DB. The route-registration check is gated by scipy + a
razorpay stub (same pattern as the other route tests).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import convergence_check

    assert set(convergence_check.__all__) == {
        "CV_CONVERGED_THRESHOLD",
        "CV_DIVERGED_THRESHOLD",
        "MIN_SIMS_FOR_VERDICT",
        "MAX_SIMS_CONSIDERED",
        "VERDICT_CONVERGED",
        "VERDICT_MILDLY_VARIANT",
        "VERDICT_DIVERGED",
        "VERDICT_INSUFFICIENT_DATA",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_convergence_check",
    }


# ---------------------------------------------------------------------------
# Empty / single-value input
# ---------------------------------------------------------------------------


def test_convergence_empty_returns_insufficient() -> None:
    from app.simulation.convergence_check import (
        VERDICT_INSUFFICIENT_DATA,
        build_convergence_check,
    )

    out = build_convergence_check([])
    assert out["sim_count"] == 0
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA


def test_convergence_zero_pcr_uses_results_json() -> None:
    """When ``predicted_conversion_rate`` is missing on the
    row, fall back to ``results_json.mean_conversion_rate``."""
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        {
            "id": 1, "status": "COMPLETED",
            "predicted_conversion_rate": None,
            "results_json": {"mean_conversion_rate": 0.04},
        },
        {
            "id": 2, "status": "COMPLETED",
            "predicted_conversion_rate": None,
            "results_json": {"mean_conversion_rate": 0.06},
        },
        {
            "id": 3, "status": "COMPLETED",
            "predicted_conversion_rate": None,
            "results_json": {"mean_conversion_rate": 0.05},
        },
    ])
    assert out["sim_count"] == 3
    assert abs(out["mean_pcr"] - 0.05) < 1e-6


def test_convergence_single_sim() -> None:
    """One sim → verdict = INSUFFICIENT_DATA, std_dev = 0."""
    from app.simulation.convergence_check import (
        VERDICT_INSUFFICIENT_DATA,
        build_convergence_check,
    )

    out = build_convergence_check([
        {"id": 1, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04},
    ])
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["std_dev"] == 0.0


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------


def test_convergence_verdict_converged() -> None:
    from app.simulation.convergence_check import (
        VERDICT_CONVERGED,
        build_convergence_check,
    )

    # CV ~ 1% (very tight spread).
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.0005}
        for i in range(5)
    ])
    assert out["verdict"] == VERDICT_CONVERGED


def test_convergence_verdict_mildly_variant() -> None:
    from app.simulation.convergence_check import (
        VERDICT_MILDLY_VARIANT,
        build_convergence_check,
    )

    # CV ~ 10% (moderate spread).
    pcrs = [0.04, 0.045, 0.05, 0.042, 0.046]
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": p}
        for i, p in enumerate(pcrs)
    ])
    assert out["verdict"] == VERDICT_MILDLY_VARIANT


def test_convergence_verdict_diverged() -> None:
    from app.simulation.convergence_check import (
        VERDICT_DIVERGED,
        build_convergence_check,
    )

    # CV ~ 50% — wide spread, predictions are not reliable.
    pcrs = [0.02, 0.06, 0.03, 0.05, 0.04]
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": p}
        for i, p in enumerate(pcrs)
    ])
    assert out["verdict"] == VERDICT_DIVERGED


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_convergence_known_cv() -> None:
    """Pin the math to a hand-computable example.

    Values: [0.04, 0.05, 0.06] → mean = 0.05,
    each |x - mean| = 0.01, squared = 0.0001
    variance = (0.0001 + 0 + 0.0001) / 3 ≈ 6.67e-05
    std_dev = sqrt(6.67e-05) ≈ 0.008165
    CV = 0.008165 / 0.05 ≈ 0.1633 (DIVERGED, >= 15%).
    """
    from app.simulation.convergence_check import (
        VERDICT_DIVERGED,
        build_convergence_check,
    )

    out = build_convergence_check([
        {"id": 1, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04},
        {"id": 2, "status": "COMPLETED",
         "predicted_conversion_rate": 0.05},
        {"id": 3, "status": "COMPLETED",
         "predicted_conversion_rate": 0.06},
    ])
    assert abs(out["mean_pcr"] - 0.05) < 1e-6
    assert abs(out["std_dev"] - 0.008165) < 1e-3
    assert abs(out["cv"] - 0.163299) < 1e-3
    assert out["verdict"] == VERDICT_DIVERGED


def test_convergence_min_max_range() -> None:
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": p}
        for i, p in enumerate(
            [0.04, 0.05, 0.03, 0.06, 0.045],
        )
    ])
    assert out["min_pcr"] == 0.03
    assert out["max_pcr"] == 0.06
    assert abs(out["range_pcr"] - 0.03) < 1e-6


def test_convergence_handles_zero_mean() -> None:
    """All-zero predictions → CV is 0 (denominator
    floored). Verdict = CONVERGED."""
    from app.simulation.convergence_check import (
        VERDICT_CONVERGED,
        build_convergence_check,
    )

    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.0}
        for i in range(5)
    ])
    assert out["cv"] == 0.0
    assert out["verdict"] == VERDICT_CONVERGED


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_convergence_handles_non_dict_entries() -> None:
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        "not-a-dict",
        None,
        {"id": 1, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04},
        {"id": 2, "status": "COMPLETED",
         "predicted_conversion_rate": 0.06},
        {"id": 3, "status": "COMPLETED",
         "predicted_conversion_rate": 0.05},
    ])
    # Non-dict rows are skipped defensively — only dict rows
    # participate in the count.
    assert out["sim_count"] == 3
    assert abs(out["mean_pcr"] - 0.05) < 1e-6


def test_convergence_skips_rows_without_pcr() -> None:
    """Rows without any usable PCR must NOT inflate
    sim_count toward the verdict threshold."""
    from app.simulation.convergence_check import (
        VERDICT_INSUFFICIENT_DATA,
        build_convergence_check,
    )

    out = build_convergence_check([
        {"id": 1, "status": "RUNNING", "predicted_conversion_rate": None},
        {"id": 2, "status": "COMPLETED", "predicted_conversion_rate": None},
        {"id": 3, "status": "COMPLETED", "predicted_conversion_rate": 0.04},
        {"id": 4, "status": "COMPLETED", "predicted_conversion_rate": 0.05},
    ])
    # Only 2 usable → INSUFFICIENT_DATA.
    assert out["verdict"] == VERDICT_INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_convergence_narrative_diverged_includes_warning() -> None:
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": p}
        for i, p in enumerate(
            [0.02, 0.06, 0.03, 0.05, 0.04],
        )
    ])
    assert "diverge" in out["narrative"].lower()
    assert (
        "assumption" in out["narrative"].lower()
        or "environment" in out["narrative"].lower()
    )


def test_convergence_narrative_converged_is_calm() -> None:
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.0005}
        for i in range(5)
    ])
    assert "stable" in out["narrative"].lower()


# ---------------------------------------------------------------------------
# Key signals
# ---------------------------------------------------------------------------


def test_convergence_key_signals_cv_present() -> None:
    from app.simulation.convergence_check import build_convergence_check

    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.0005}
        for i in range(5)
    ])
    sig = next(
        s for s in out["key_signals"] if s["label"] == "cv"
    )
    assert sig["value"] == out["cv"]


def test_convergence_key_signals_cv_severity_mapping() -> None:
    from app.simulation.convergence_check import (
        SIGNAL_CRITICAL,
        SIGNAL_OK,
        SIGNAL_WATCH,
        build_convergence_check,
    )

    # Converged → ok
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.0001}
        for i in range(5)
    ])
    sig = next(
        s for s in out["key_signals"] if s["label"] == "cv"
    )
    assert sig["severity"] == SIGNAL_OK

    # Mildly variant → watch
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.004}
        for i in range(5)
    ])
    sig = next(
        s for s in out["key_signals"] if s["label"] == "cv"
    )
    assert sig["severity"] == SIGNAL_WATCH

    # Diverged → critical
    out = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.01 * (i + 1)}
        for i in range(5)
    ])
    sig = next(
        s for s in out["key_signals"] if s["label"] == "cv"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_convergence_out_default_shape() -> None:
    from app.schemas.project import ConvergenceCheckOut

    out = ConvergenceCheckOut()
    assert out.sim_count == 0
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_convergence_out_round_trips_helper_payload() -> None:
    from app.schemas.project import ConvergenceCheckOut
    from app.simulation.convergence_check import build_convergence_check

    payload = build_convergence_check([
        {"id": i, "status": "COMPLETED",
         "predicted_conversion_rate": 0.04 + i * 0.0005}
        for i in range(5)
    ])
    out = ConvergenceCheckOut(**payload)
    assert out.sim_count == 5
    assert out.verdict == "CONVERGED"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_convergence_route_registered() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import projects as proj_mod

    paths = {r.path for r in proj_mod.router.routes}
    assert "/projects/{project_id}/convergence" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/projects/{project_id}/convergence"]
    )
