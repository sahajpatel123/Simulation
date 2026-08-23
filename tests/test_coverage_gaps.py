"""Tests for the per-user coverage-gap helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations



# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import coverage_gaps

    assert set(coverage_gaps.__all__) == {
        "STANDARD_CATEGORIES",
        "THIN_CLUSTER_COVERAGE",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_coverage_gaps",
    }


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_digest_empty_returns_zero_state() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps()
    assert out["covered_categories"] == []
    assert out["total_assumption_count"] == 0
    # No categories → all standard categories missing.
    assert out["covered_cluster_count"] == 0


# ---------------------------------------------------------------------------
# Category coverage
# ---------------------------------------------------------------------------


def test_digest_categories_covered() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": False},
            {"category": "Trust", "sensitivity": "MEDIUM",
             "is_hidden": False},
            {"category": "Pricing", "sensitivity": "MEDIUM",
             "is_hidden": False},
        ],
    )
    assert "Pricing" in out["covered_categories"]
    assert "Trust" in out["covered_categories"]


def test_digest_categories_missing_vs_standard() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": False},
        ],
    )
    # Pricing is the only category covered; everything
    # else in STANDARD_CATEGORIES is missing.
    assert "Pricing" not in out["missing_categories"]
    assert "Trust" in out["missing_categories"]
    assert "Retention" in out["missing_categories"]


def test_digest_filters_hidden() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": True},
        ],
    )
    assert "Pricing" not in out["covered_categories"]
    assert out["total_assumption_count"] == 0


# ---------------------------------------------------------------------------
# Sensitivity breakdown
# ---------------------------------------------------------------------------


def test_digest_sensitivity_breakdown() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            {"category": "x", "sensitivity": "HIGH",
             "is_hidden": False},
            {"category": "x", "sensitivity": "HIGH",
             "is_hidden": False},
            {"category": "x", "sensitivity": "LOW",
             "is_hidden": False},
        ],
    )
    assert out["sensitivity_breakdown"] == {"HIGH": 2, "LOW": 1}


# ---------------------------------------------------------------------------
# Cluster coverage
# ---------------------------------------------------------------------------


def test_digest_cluster_count_distinct() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        cluster_ids=[1, 2, 3, 2, 1],
    )
    assert out["covered_cluster_count"] == 3


def test_digest_empty_cluster_ids() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(cluster_ids=None)
    assert out["covered_cluster_count"] == 0


# ---------------------------------------------------------------------------
# Key signals
# ---------------------------------------------------------------------------


def test_digest_key_signal_missing_categories() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps()
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "missing_categories"
    )
    assert sig["value"] >= 1


def test_digest_no_signal_for_total_when_present() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": False},
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "total_assumption_count"
    )
    assert sig["severity"] == "ok"


def test_digest_key_signal_thin_cluster_coverage() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        cluster_ids=[1, 2],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "thin_cluster_coverage"
    )
    assert sig["value"] == 2
    assert sig["severity"] == "watch"


def test_digest_key_signal_no_high_sensitivity() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    # 5 LOW-sensitivity assumptions → no HIGH/CRITICAL →
    # critical signal fires.
    out = build_coverage_gaps(
        assumptions=[
            {
                "category": "Pricing", "sensitivity": "LOW",
                "is_hidden": False,
            }
            for _ in range(5)
        ],
    )
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "no_high_sensitivity_assumptions"
    )
    assert sig["severity"] == "critical"


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------


def test_digest_handles_non_dict_entries() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(
        assumptions=[
            "not-a-dict",
            None,
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": False},
        ],
    )
    assert out["total_assumption_count"] == 1


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_digest_narrative_mentions_missing_categories() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps()
    assert "Missing:" in out["narrative"]


def test_digest_narrative_mentions_thin_coverage() -> None:
    from app.simulation.coverage_gaps import build_coverage_gaps

    out = build_coverage_gaps(cluster_ids=[1])
    assert "cluster" in out["narrative"].lower()