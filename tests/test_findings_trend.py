"""
Tests for the findings-trend helper + schema + route
registration.

The trend logic is pure-Python so we can exercise it without
spinning up Postgres. The DB-touching route is smoke-tested
via the route-registration pattern (gated by scipy).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import findings_trend

    assert set(findings_trend.__all__) == {
        "VALID_SEVERITIES",
        "DEFAULT_MIN_SEVERITY",
        "LABEL_IMPROVING",
        "LABEL_DEGRADING",
        "LABEL_STABLE",
        "LABEL_UNKNOWN",
        "VALID_DIRECTIONS",
        "normalise_severity",
        "severity_meets_min",
        "build_findings_trend",
    }


def test_severity_allowlist_pinned() -> None:
    from app.simulation.findings_trend import VALID_SEVERITIES

    assert set(VALID_SEVERITIES) == {"CRITICAL", "WARNING", "INFO"}


def test_direction_allowlist_pinned() -> None:
    from app.simulation.findings_trend import VALID_DIRECTIONS

    assert set(VALID_DIRECTIONS) == {
        "IMPROVING",
        "DEGRADING",
        "STABLE",
        "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# normalise_severity
# ---------------------------------------------------------------------------


def test_normalise_severity_default_is_info() -> None:
    from app.simulation.findings_trend import normalise_severity

    assert normalise_severity(None) == "INFO"
    assert normalise_severity("") == "INFO"
    assert normalise_severity("  ") == "INFO"


def test_normalise_severity_accepts_uppercase() -> None:
    from app.simulation.findings_trend import normalise_severity

    assert normalise_severity("critical") == "CRITICAL"
    assert normalise_severity("  Warning  ") == "WARNING"


def test_normalise_severity_rejects_unknown() -> None:
    from app.simulation.findings_trend import normalise_severity

    with pytest.raises(ValueError):
        normalise_severity("fatal")


def test_severity_meets_min_monotonic() -> None:
    from app.simulation.findings_trend import severity_meets_min

    assert severity_meets_min("CRITICAL", "INFO")
    assert severity_meets_min("CRITICAL", "CRITICAL")
    assert not severity_meets_min("INFO", "CRITICAL")
    assert not severity_meets_min("WARNING", "CRITICAL")
    assert severity_meets_min("WARNING", "INFO")


# ---------------------------------------------------------------------------
# build_findings_trend — empty / malformed input
# ---------------------------------------------------------------------------


def test_trend_empty_rows_returns_unknown() -> None:
    from app.simulation.findings_trend import build_findings_trend

    out = build_findings_trend([])
    assert out["bin_size"] == "day"
    assert out["min_severity"] == "INFO"
    assert out["bins"] == []
    assert out["overall_direction"] == "UNKNOWN"
    assert out["first_bin_critical"] == 0
    assert out["last_bin_critical"] == 0
    assert out["mean_delta_critical"] is None
    assert out["peak_critical_bin"] is None


def test_trend_skips_sims_with_no_findings() -> None:
    """A sim whose findings list is None / empty / not a list
    is skipped, not crashed."""
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (datetime(2026, 1, 15, tzinfo=UTC), None),
        (datetime(2026, 2, 15, tzinfo=UTC), []),
        (datetime(2026, 3, 15, tzinfo=UTC), "not a list"),
    ]
    out = build_findings_trend(rows)
    assert out["bins"] == []


# ---------------------------------------------------------------------------
# Bin grouping
# ---------------------------------------------------------------------------


def _finding(severity: str) -> dict:
    return {
        "architect_name": "PricingArchitect",
        "severity": severity,
    }


def test_trend_groups_by_day_by_default() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL"), _finding("WARNING")],
        ),
        (
            datetime(2026, 1, 5, 18, tzinfo=UTC),
            [_finding("INFO")],
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
    ]
    out = build_findings_trend(rows)
    bins = out["bins"]
    assert len(bins) == 2
    # Day 1: 1 CRITICAL, 1 WARNING, 1 INFO.
    assert bins[0]["bin"] == "2026-01-05"
    assert bins[0]["critical_count"] == 1
    assert bins[0]["warning_count"] == 1
    assert bins[0]["info_count"] == 1
    assert bins[0]["finding_count"] == 3
    # Day 2: 1 CRITICAL.
    assert bins[1]["bin"] == "2026-01-06"
    assert bins[1]["critical_count"] == 1


def test_trend_groups_by_week_when_requested() -> None:
    from app.simulation.findings_trend import (
        BIN_WEEK,
        build_findings_trend,
    )

    rows = [
        # Mon + Wed = same week.
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
        (
            datetime(2026, 1, 7, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
        # Next Monday.
        (
            datetime(2026, 1, 12, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
    ]
    out = build_findings_trend(rows, bin_size=BIN_WEEK)
    bins = out["bins"]
    assert len(bins) == 2
    assert bins[0]["critical_count"] == 2
    assert bins[1]["critical_count"] == 1


# ---------------------------------------------------------------------------
# min_severity filter
# ---------------------------------------------------------------------------


def test_trend_min_severity_critical_excludes_lower() -> None:
    """min_severity=CRITICAL → WARNING + INFO findings are
    skipped entirely from bin counts."""
    from app.simulation.findings_trend import (
        build_findings_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [
                _finding("CRITICAL"),
                _finding("WARNING"),
                _finding("INFO"),
            ],
        ),
    ]
    out = build_findings_trend(rows, min_severity="CRITICAL")
    assert out["bins"][0]["critical_count"] == 1
    assert out["bins"][0]["warning_count"] == 0
    assert out["bins"][0]["info_count"] == 0


def test_trend_min_severity_warning_excludes_info() -> None:
    from app.simulation.findings_trend import (
        build_findings_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [
                _finding("CRITICAL"),
                _finding("WARNING"),
                _finding("INFO"),
            ],
        ),
    ]
    out = build_findings_trend(rows, min_severity="WARNING")
    assert out["bins"][0]["critical_count"] == 1
    assert out["bins"][0]["warning_count"] == 1
    assert out["bins"][0]["info_count"] == 0


# ---------------------------------------------------------------------------
# Direction label
# ---------------------------------------------------------------------------


def test_trend_overall_direction_improving_when_critical_drops() -> None:
    """CRITICAL count went from 5 to 2 → IMPROVING (fewer)."""
    from app.simulation.findings_trend import (
        LABEL_IMPROVING,
        build_findings_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")] * 5,
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 2,
        ),
    ]
    out = build_findings_trend(rows)
    assert out["overall_direction"] == LABEL_IMPROVING


def test_trend_overall_direction_degrading_when_critical_grows() -> None:
    from app.simulation.findings_trend import (
        LABEL_DEGRADING,
        build_findings_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 5,
        ),
    ]
    out = build_findings_trend(rows)
    assert out["overall_direction"] == LABEL_DEGRADING


def test_trend_overall_direction_stable_when_unchanged() -> None:
    from app.simulation.findings_trend import (
        LABEL_STABLE,
        build_findings_trend,
    )

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
    ]
    out = build_findings_trend(rows)
    assert out["overall_direction"] == LABEL_STABLE


# ---------------------------------------------------------------------------
# peak_critical_bin
# ---------------------------------------------------------------------------


def test_trend_peak_critical_bin_none_when_no_criticals() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("WARNING")],
        ),
    ]
    out = build_findings_trend(rows)
    assert out["peak_critical_bin"] is None


def test_trend_peak_critical_bin_picks_highest_count() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")] * 2,
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 7,
        ),
        (
            datetime(2026, 1, 7, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
    ]
    out = build_findings_trend(rows)
    peak = out["peak_critical_bin"]
    assert peak["bin"] == "2026-01-06"
    assert peak["critical_count"] == 7


def test_trend_peak_critical_bin_tiebreak_by_latest_bin() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
    ]
    out = build_findings_trend(rows)
    # Both have 3 CRITICALs → later bin (Jan 6) wins.
    assert out["peak_critical_bin"]["bin"] == "2026-01-06"


# ---------------------------------------------------------------------------
# Defensive coercion
# ---------------------------------------------------------------------------


def test_trend_skips_non_numeric_severity_gracefully() -> None:
    """A severity that's not in the allowlist is SKIPPED, not
    silently counted as INFO. Counting unknowns as INFO would
    inflate the buckets."""
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [
                {"architect_name": "PricingArchitect", "severity": "FOO"},
                _finding("CRITICAL"),
            ],
        ),
    ]
    out = build_findings_trend(rows)
    # FOO → skipped (not in allowlist). Only the CRITICAL remains.
    assert out["bins"][0]["info_count"] == 0
    assert out["bins"][0]["critical_count"] == 1


def test_trend_skips_non_dict_findings() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [
                "not a dict",
                _finding("CRITICAL"),
            ],
        ),
    ]
    out = build_findings_trend(rows)
    assert out["bins"][0]["critical_count"] == 1


def test_trend_skips_invalid_iso_strings() -> None:
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            "not-a-timestamp",
            [_finding("CRITICAL")],
        ),
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
    ]
    out = build_findings_trend(rows)
    assert len(out["bins"]) == 1


# ---------------------------------------------------------------------------
# critical_finding_distribution + totals
# ---------------------------------------------------------------------------


def test_trend_critical_distribution_default_when_empty() -> None:
    from app.simulation.findings_trend import build_findings_trend

    out = build_findings_trend([])
    assert out["critical_finding_distribution"] == {
        "zero": 0, "low": 0, "moderate": 0, "high": 0,
    }
    assert out["total_finding_count"] == 0


def test_trend_critical_distribution_bucketing() -> None:
    """Each bin's critical_count is bucketed into
    zero / low (1-2) / moderate (3-5) / high (6+)."""
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        # zero (0 criticals)
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            [_finding("WARNING")],
        ),
        # zero (no findings)
        (
            datetime(2026, 1, 2, tzinfo=UTC),
            [_finding("WARNING"), _finding("INFO")],
        ),
        # low (1 critical)
        (
            datetime(2026, 1, 3, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
        # low (2 criticals)
        (
            datetime(2026, 1, 4, tzinfo=UTC),
            [_finding("CRITICAL")] * 2,
        ),
        # moderate (3 criticals)
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
        # high (6 criticals)
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 6,
        ),
    ]
    out = build_findings_trend(rows)
    assert out["critical_finding_distribution"] == {
        "zero": 2,
        "low": 2,
        "moderate": 1,
        "high": 1,
    }


def test_trend_critical_distribution_boundary_at_2_and_5() -> None:
    """Bucket boundaries: 2 → low (≤2), 3 → moderate (≤5),
    5 → moderate (≤5), 6 → high."""
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            [_finding("CRITICAL")] * 2,
        ),
        (
            datetime(2026, 1, 2, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
        (
            datetime(2026, 1, 3, tzinfo=UTC),
            [_finding("CRITICAL")] * 5,
        ),
        (
            datetime(2026, 1, 4, tzinfo=UTC),
            [_finding("CRITICAL")] * 6,
        ),
    ]
    out = build_findings_trend(rows)
    d = out["critical_finding_distribution"]
    assert d["low"] == 1
    assert d["moderate"] == 2  # 3 and 5 both moderate
    assert d["high"] == 1


def test_trend_totals_sum_across_bins() -> None:
    """total_finding_count is the sum of every per-severity
    count across every bin."""
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            [_finding("CRITICAL")] * 3
            + [_finding("WARNING")] * 2
            + [_finding("INFO")] * 1,
        ),
        (
            datetime(2026, 1, 2, tzinfo=UTC),
            [_finding("CRITICAL")] * 1
            + [_finding("WARNING")] * 1
            + [_finding("INFO")] * 4,
        ),
    ]
    out = build_findings_trend(rows)
    assert out["total_critical_count"] == 4
    assert out["total_warning_count"] == 3
    assert out["total_info_count"] == 5
    assert out["total_finding_count"] == 12


def test_trend_totals_zero_when_no_data() -> None:
    from app.simulation.findings_trend import build_findings_trend

    out = build_findings_trend([])
    assert out["total_finding_count"] == 0
    assert out["total_critical_count"] == 0
    assert out["total_warning_count"] == 0
    assert out["total_info_count"] == 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_findings_trend_out_default_shape() -> None:
    from app.schemas.simulation import FindingsTrendOut

    out = FindingsTrendOut()
    assert out.bin_size == "day"
    assert out.min_severity == "INFO"
    assert out.bins == []
    assert out.overall_direction == "UNKNOWN"
    assert out.first_bin_critical == 0
    assert out.last_bin_critical == 0
    assert out.mean_delta_critical is None
    assert out.peak_critical_bin is None
    assert out.critical_finding_distribution == {}
    assert out.total_finding_count == 0
    assert out.total_critical_count == 0
    assert out.total_warning_count == 0
    assert out.total_info_count == 0


def test_findings_trend_out_round_trips_helper_payload() -> None:
    """The route layer must wrap ``build_findings_trend(...)``
    output directly into the Pydantic schema without coercion
    errors."""
    from app.schemas.simulation import FindingsTrendOut
    from app.simulation.findings_trend import build_findings_trend

    rows = [
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            [_finding("CRITICAL")],
        ),
        (
            datetime(2026, 1, 6, tzinfo=UTC),
            [_finding("CRITICAL")] * 3,
        ),
    ]
    payload = build_findings_trend(rows)
    out = FindingsTrendOut(**payload)
    assert out.first_bin_critical == 1
    assert out.last_bin_critical == 3
    assert out.mean_delta_critical == 2


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_findings_trend_route_registered() -> None:
    """GET /simulations/findings-trend must appear in the router."""
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
    assert "/simulations/findings-trend" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert "GET" in methods_by_path["/simulations/findings-trend"]


def test_findings_trend_route_query_params() -> None:
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
            r.path == "/simulations/findings-trend"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "since" in query_param_names
            assert "until" in query_param_names
            assert "bin" in query_param_names
            assert "min_severity" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/findings-trend route not found"
    )
