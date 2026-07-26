"""
Tests for the cross-simulation architect accuracy bridge helper
+ schema + route registration.

The bridge logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested via
the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# severity helpers
# ---------------------------------------------------------------------------


def test_normalise_severity_default_and_uppercases() -> None:
    from app.simulation.architect_accuracy_bridge import normalise_severity

    assert normalise_severity(None) == "INFO"
    assert normalise_severity("") == "INFO"
    assert normalise_severity("  ") == "INFO"
    assert normalise_severity("warning") == "WARNING"


def test_normalise_severity_rejects_unknown() -> None:
    from app.simulation.architect_accuracy_bridge import normalise_severity

    with pytest.raises(ValueError):
        normalise_severity("crit")
    with pytest.raises(ValueError):
        normalise_severity("fatal")


def test_severity_meets_min_monotonic() -> None:
    from app.simulation.architect_accuracy_bridge import (
        severity_meets_min,
    )

    assert severity_meets_min("CRITICAL", "INFO")
    assert severity_meets_min("CRITICAL", "CRITICAL")
    assert not severity_meets_min("INFO", "CRITICAL")
    assert not severity_meets_min("WARNING", "CRITICAL")


# ---------------------------------------------------------------------------
# normalise_top_n
# ---------------------------------------------------------------------------


def test_normalise_top_n_default_and_bounds() -> None:
    from app.simulation.architect_accuracy_bridge import (
        DEFAULT_TOP_N,
        MAX_TOP_N,
        normalise_top_n,
    )

    assert normalise_top_n(None) == DEFAULT_TOP_N
    assert normalise_top_n(0) == 1
    assert normalise_top_n(-5) == 1
    assert normalise_top_n(MAX_TOP_N + 1) == MAX_TOP_N
    assert normalise_top_n(25) == 25


# ---------------------------------------------------------------------------
# bridge_architect_accuracy — empty / malformed input
# ---------------------------------------------------------------------------


def test_bridge_empty_input_returns_zero_summary() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([])
    assert out["by_architect"] == []
    assert out["most_biased_architects"] == []
    assert out["simulation_count"] == 0
    assert out["outcome_attached_sim_count"] == 0
    assert out["tighten_count"] == 0
    assert out["loosen_count"] == 0
    assert out["trusted_count"] == 0
    assert out["insufficient_data_count"] == 0
    assert out["min_severity"] == "INFO"


def test_bridge_handles_missing_results_json() -> None:
    """Defensive — None / non-dict payloads shouldn't crash."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        (None, (0.10, 0.05)),
        ({}, (0.20, 0.10)),
        ([], (0.30, 0.20)),
        ("not a dict", (0.40, 0.30)),
    ])
    assert out["simulation_count"] == 4
    # No findings → no per-architect rows.
    assert out["by_architect"] == []


# ---------------------------------------------------------------------------
# bridge_architect_accuracy — per-architect stats
# ---------------------------------------------------------------------------


def _finding(architect: str, severity: str, impact: float = 0.0) -> dict:
    return {
        "architect_name": architect,
        "severity": severity,
        "conversion_impact": impact,
    }


def _sim(*findings: dict, outcome: tuple[float, float] | None = None):
    """Build ``(results_json, (predicted, actual))`` pair."""
    return ({"domain_findings": list(findings)}, outcome or (None, None))


def test_bridge_counts_findings_per_architect() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            _finding("pricing", "WARNING"),
            _finding("trust", "INFO"),
            outcome=(0.20, 0.10),
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.15, 0.10),
        ),
    ])
    by_arch = {r["architect_name"]: r for r in out["by_architect"]}
    assert by_arch["pricing"]["finding_count"] == 3
    assert by_arch["pricing"]["critical_count"] == 2
    assert by_arch["pricing"]["warning_count"] == 1
    assert by_arch["trust"]["finding_count"] == 1
    assert by_arch["trust"]["info_count"] == 1


def test_bridge_calibration_variance_is_mean_of_per_sim_variances() -> None:
    """For each architect, the calibration_variance is the mean
    (predicted − actual) across sims where they had findings."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    # Pricing flagged CRITICAL on sim1 (over by 0.10) and sim2
    # (over by 0.20) → mean = 0.15 → OVER_PREDICTS.
    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 2
    assert pricing["calibration_variance"] == pytest.approx(0.15)
    assert pricing["calibration_direction"] == "OVER_PREDICTS"
    assert pricing["needs_review"] is True


def test_bridge_under_prediction_detected() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    # Trust flagged CRITICAL on sim1 (under by 0.05) and sim2
    # (under by 0.10) → mean = -0.075 → UNDER_PREDICTS.
    out = bridge_architect_accuracy([
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.05, 0.10),
        ),
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.00, 0.10),
        ),
    ])
    trust = next(
        r for r in out["by_architect"] if r["architect_name"] == "trust"
    )
    assert trust["calibration_variance"] == pytest.approx(-0.075)
    assert trust["calibration_direction"] == "UNDER_PREDICTS"
    assert trust["needs_review"] is True


def test_bridge_balanced_label_for_small_variance() -> None:
    """Variance within ±2pp → BALANCED, not over/under."""
    from app.simulation.architect_accuracy_bridge import (
        CALIBRATION_BIAS_THRESHOLD,
        bridge_architect_accuracy,
    )

    # ±1pp → within threshold → BALANCED.
    delta = CALIBRATION_BIAS_THRESHOLD * 0.5
    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.10 + delta, 0.10),
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.10 - delta, 0.10),
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert abs(pricing["calibration_variance"]) < CALIBRATION_BIAS_THRESHOLD
    assert pricing["calibration_direction"] == "BALANCED"
    assert pricing["needs_review"] is False


def test_bridge_insufficient_data_when_no_outcomes() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    # Findings present but no outcome → INSUFFICIENT_DATA.
    out = bridge_architect_accuracy([
        _sim(_finding("pricing", "CRITICAL")),  # outcome=None
        _sim(_finding("pricing", "CRITICAL")),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 0
    assert pricing["calibration_direction"] == "INSUFFICIENT_DATA"
    assert pricing["needs_review"] is False


def test_bridge_sim_without_findings_excluded_from_calibration() -> None:
    """A sim with no findings at all can't contribute to anyone's
    calibration_variance — only sims where the architect
    *flagged* something feed the per-architect mean."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        # pricing flagged here.
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),  # over by 0.10
        ),
        # pricing did NOT flag here — must NOT feed its calibration.
        _sim(outcome=(0.30, 0.10)),  # over by 0.20
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    # Only the first sim feeds → variance = 0.10.
    assert pricing["calibrated_sim_count"] == 1
    assert pricing["calibration_variance"] == pytest.approx(0.10)


def test_bridge_outcome_attached_sim_count_uniques() -> None:
    """Multiple findings in one sim still count as ONE
    outcome-attached sim."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            _finding("trust", "WARNING"),
            outcome=(0.20, 0.10),
        ),
        _sim(
            _finding("pricing", "WARNING"),
            _finding("trust", "INFO"),
            outcome=(0.15, 0.10),
        ),
        # Findings but no outcome — NOT counted.
        _sim(_finding("pricing", "CRITICAL")),
    ])
    assert out["outcome_attached_sim_count"] == 2


def test_bridge_skips_non_numeric_outcomes() -> None:
    """A missing or non-numeric outcome side must not feed
    calibration — same defensive coercion as outcomes_digest."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(None, 0.10),  # missing predicted
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, None),  # missing actual
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),  # good
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 1


def test_bridge_filters_findings_by_min_severity() -> None:
    """``min_severity=CRITICAL`` excludes WARNING and INFO findings
    from the rollup."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            _finding("pricing", "WARNING"),
            _finding("pricing", "INFO"),
            outcome=(0.20, 0.10),
        ),
    ], min_severity="CRITICAL")
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["finding_count"] == 1
    assert pricing["critical_count"] == 1
    assert pricing["warning_count"] == 0
    assert pricing["info_count"] == 0


# ---------------------------------------------------------------------------
# bridge_architect_accuracy — sorting / top_n
# ---------------------------------------------------------------------------


def test_bridge_sorted_by_abs_variance_desc() -> None:
    """Most-biased architect first."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        # trust: under by 0.10 → |variance|=0.10
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.00, 0.10),
        ),
        # pricing: over by 0.20 → |variance|=0.20
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),
        ),
    ])
    names = [r["architect_name"] for r in out["by_architect"]]
    assert names == ["pricing", "trust"]


def test_bridge_most_biased_first_n() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    sims = [
        _sim(
            _finding(f"a{i}", "CRITICAL"),
            outcome=(0.20 + i * 0.01, 0.10),  # increasing over-prediction
        )
        for i in range(6)
    ]
    out = bridge_architect_accuracy(sims, top_n=3)
    assert len(out["most_biased_architects"]) == 3
    # a5 (variance=0.15) > a4 (0.14) > a3 (0.13) → most biased first.
    assert out["most_biased_architects"][0] == "a5"
    assert out["most_biased_architects"][1] == "a4"
    assert out["most_biased_architects"][2] == "a3"


def test_bridge_default_top_n_is_five() -> None:
    from app.simulation.architect_accuracy_bridge import (
        DEFAULT_TOP_N,
        bridge_architect_accuracy,
    )

    sims = [
        _sim(
            _finding(f"a{i}", "CRITICAL"),
            outcome=(0.20 + i * 0.01, 0.10),
        )
        for i in range(8)
    ]
    out = bridge_architect_accuracy(sims)
    assert len(out["most_biased_architects"]) == min(DEFAULT_TOP_N, 8)


# ---------------------------------------------------------------------------
# coverage + recommendation
# ---------------------------------------------------------------------------


def test_bridge_finding_only_sim_count_when_outcome_missing() -> None:
    """When a sim has findings but no usable outcome, the
    architect's ``finding_only_sim_count`` goes up by 1 and the
    calibrated count does not."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        # Findings + outcome → calibrated.
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),
        ),
        # Findings + no outcome → finding-only.
        _sim(_finding("pricing", "CRITICAL")),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 1
    assert pricing["finding_only_sim_count"] == 1


def test_bridge_ground_truth_coverage_fraction() -> None:
    """``ground_truth_coverage`` = calibrated / (calibrated +
    finding_only). 1 calibrated + 3 finding-only → 0.25."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),
        ),
        _sim(_finding("pricing", "CRITICAL")),
        _sim(_finding("pricing", "CRITICAL")),
        _sim(_finding("pricing", "CRITICAL")),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 1
    assert pricing["finding_only_sim_count"] == 3
    assert pricing["ground_truth_coverage"] == pytest.approx(0.25)


def test_bridge_ground_truth_coverage_full_when_all_calibrated() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["finding_only_sim_count"] == 0
    assert pricing["ground_truth_coverage"] == pytest.approx(1.0)


def test_bridge_recommendation_tighten_for_over_predicter() -> None:
    from app.simulation.architect_accuracy_bridge import (
        LABEL_TIGHTEN,
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),  # over by 0.20
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.25, 0.10),  # over by 0.15
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibration_direction"] == "OVER_PREDICTS"
    assert pricing["recommendation"] == LABEL_TIGHTEN


def test_bridge_recommendation_loosen_for_under_predicter() -> None:
    from app.simulation.architect_accuracy_bridge import (
        LABEL_LOOSEN,
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.00, 0.10),  # under by 0.10
        ),
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.05, 0.10),  # under by 0.05
        ),
    ])
    trust = next(
        r for r in out["by_architect"] if r["architect_name"] == "trust"
    )
    assert trust["calibration_direction"] == "UNDER_PREDICTS"
    assert trust["recommendation"] == LABEL_LOOSEN


def test_bridge_recommendation_trusted_for_balanced() -> None:
    from app.simulation.architect_accuracy_bridge import (
        LABEL_TRUSTED,
        bridge_architect_accuracy,
    )

    # variance = 0.0 → BALANCED → TRUSTED.
    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.10, 0.10),
        ),
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.10, 0.10),
        ),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibration_direction"] == "BALANCED"
    assert pricing["recommendation"] == LABEL_TRUSTED


def test_bridge_recommendation_insufficient_data_when_no_outcomes() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    # Findings but every sim is missing the outcome side →
    # finding_only count rises, no calibration data, recommendation
    # is INSUFFICIENT_DATA.
    out = bridge_architect_accuracy([
        _sim(_finding("pricing", "CRITICAL")),
        _sim(_finding("pricing", "CRITICAL")),
    ])
    pricing = next(
        r for r in out["by_architect"] if r["architect_name"] == "pricing"
    )
    assert pricing["calibrated_sim_count"] == 0
    assert pricing["calibration_direction"] == "INSUFFICIENT_DATA"
    assert pricing["recommendation"] == "INSUFFICIENT_DATA"


def test_bridge_recommendation_allowlist_pinned() -> None:
    """Lock the recommendation enum so a rename breaks here
    rather than silently at the dashboard."""
    from app.simulation.architect_accuracy_bridge import (
        VALID_RECOMMENDATIONS,
    )

    assert set(VALID_RECOMMENDATIONS) == {
        "TIGHTEN",
        "LOOSEN",
        "TRUSTED",
        "INSUFFICIENT_DATA",
    }


def test_bridge_top_level_action_counts() -> None:
    """tighten / loosen / trusted / insufficient_data_count
    summarise the per-architect rollup so the dashboard can show
    four summary tiles."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        # pricing over-predicts → TIGHTEN.
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),
        ),
        # trust under-predicts → LOOSEN.
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.00, 0.10),
        ),
        # onboarding balanced → TRUSTED.
        _sim(
            _finding("onboarding", "INFO"),
            outcome=(0.10, 0.10),
        ),
        # retention flagged but no outcomes → INSUFFICIENT_DATA.
        _sim(_finding("retention", "CRITICAL")),
    ])
    assert out["tighten_count"] == 1
    assert out["loosen_count"] == 1
    assert out["trusted_count"] == 1
    assert out["insufficient_data_count"] == 1


def test_bridge_top_level_counts_zero_for_empty_input() -> None:
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([])
    assert out["tighten_count"] == 0
    assert out["loosen_count"] == 0
    assert out["trusted_count"] == 0
    assert out["insufficient_data_count"] == 0


def test_bridge_recommendation_and_direction_consistent() -> None:
    """Defensive — direction and recommendation must agree (no
    OVER_PREDICTS row labelled TRUSTED, etc.)."""
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    out = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.30, 0.10),  # over
        ),
        _sim(
            _finding("trust", "CRITICAL"),
            outcome=(0.00, 0.10),  # under
        ),
        _sim(
            _finding("onboarding", "INFO"),
            outcome=(0.10, 0.10),  # balanced
        ),
        _sim(_finding("retention", "CRITICAL")),  # no outcome
    ])
    expected = {
        "OVER_PREDICTS": "TIGHTEN",
        "UNDER_PREDICTS": "LOOSEN",
        "BALANCED": "TRUSTED",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    }
    by_arch = {r["architect_name"]: r for r in out["by_architect"]}
    for arch, row in by_arch.items():
        assert row["recommendation"] == expected[row["calibration_direction"]], (
            f"{arch}: {row['calibration_direction']} → "
            f"{row['recommendation']}, expected {expected[row['calibration_direction']]}"
        )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces as
    an import error rather than a silent attribute miss in the
    route."""
    from app.simulation import architect_accuracy_bridge

    assert set(architect_accuracy_bridge.__all__) == {
        "DEFAULT_TOP_N",
        "MAX_TOP_N",
        "DEFAULT_MIN_SEVERITY",
        "VALID_SEVERITIES",
        "VALID_CALIBRATION_DIRECTIONS",
        "VALID_RECOMMENDATIONS",
        "LABEL_OVER_PREDICTS",
        "LABEL_UNDER_PREDICTS",
        "LABEL_BALANCED",
        "LABEL_INSUFFICIENT_DATA",
        "LABEL_TIGHTEN",
        "LABEL_LOOSEN",
        "LABEL_TRUSTED",
        "CALIBRATION_BIAS_THRESHOLD",
        "severity_meets_min",
        "normalise_severity",
        "normalise_top_n",
        "bridge_architect_accuracy",
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_bridge_out_default_shape() -> None:
    from app.schemas.simulation import ArchitectAccuracyBridgeOut

    out = ArchitectAccuracyBridgeOut()
    assert out.by_architect == []
    assert out.most_biased_architects == []
    assert out.simulation_count == 0
    assert out.outcome_attached_sim_count == 0
    assert out.tighten_count == 0
    assert out.loosen_count == 0
    assert out.trusted_count == 0
    assert out.insufficient_data_count == 0
    assert out.min_severity == "INFO"


def test_bridge_out_round_trips_aggregate_payload() -> None:
    """The route layer must wrap ``bridge_architect_accuracy(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import ArchitectAccuracyBridgeOut
    from app.simulation.architect_accuracy_bridge import (
        bridge_architect_accuracy,
    )

    payload = bridge_architect_accuracy([
        _sim(
            _finding("pricing", "CRITICAL"),
            outcome=(0.20, 0.10),
        ),
    ])
    out = ArchitectAccuracyBridgeOut(**payload)
    assert out.simulation_count == 1
    assert out.outcome_attached_sim_count == 1
    assert out.by_architect[0]["architect_name"] == "pricing"
    assert out.by_architect[0]["calibration_direction"] == "OVER_PREDICTS"
    assert out.most_biased_architects == ["pricing"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_bridge_route_registered() -> None:
    """GET /simulations/aggregate/architect-accuracy must appear in
    the router."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/aggregate/architect-accuracy" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path["/simulations/aggregate/architect-accuracy"]
    )


def test_bridge_route_query_params() -> None:
    """Pin the query-param surface so the UI contract is
    documented."""
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy"
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if (
            r.path == "/simulations/aggregate/architect-accuracy"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "min_severity" in query_param_names
            assert "top_n" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/aggregate/architect-accuracy route not found"
    )