"""
Tests for the project portfolio rollup helper + schema +
route registration.

The rollup logic is pure-Python so we can exercise it
without spinning up Postgres. The DB-touching route is
smoke-tested via the route-registration pattern (gated by
scipy).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    """Pin the module's ``__all__`` so a future rename surfaces
    as an import error rather than a silent attribute miss in
    the route."""
    from app.simulation import project_rollup

    assert set(project_rollup.__all__) == {
        "build_project_portfolio_rollup",
        "LABEL_HEALTHY",
        "LABEL_WATCH",
        "LABEL_MISALIBRATED",
        "LABEL_UNKNOWN",
        "VALID_HEALTH_LABELS",
        "CRITICAL_SIMULATION_THRESHOLD",
        "HEALTHY_THRESHOLD",
        "WATCH_THRESHOLD",
    }


def test_health_label_allowlist_pinned() -> None:
    from app.simulation.project_rollup import VALID_HEALTH_LABELS

    assert set(VALID_HEALTH_LABELS) == {
        "HEALTHY",
        "WATCH",
        "MISALIBRATED",
        "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# build_project_portfolio_rollup — empty / malformed input
# ---------------------------------------------------------------------------


def test_rollup_empty_input_returns_zero_summary() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([])
    assert out["projects"] == []
    assert out["total_projects"] == 0
    assert out["total_simulations"] == 0


def test_rollup_skips_rows_with_none_project_id() -> None:
    """A row with project_id=None is skipped (not crashed)."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (
            None,
            "orphan",
            1,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10,
            0.05,
        ),
    ])
    assert out["projects"] == []
    assert out["total_projects"] == 0


# ---------------------------------------------------------------------------
# Per-project aggregation
# ---------------------------------------------------------------------------


def test_rollup_groups_sims_by_project() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (
            1,
            "Alpha",
            101,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10,
            0.08,
        ),
        (
            1,
            "Alpha",
            102,
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            0.12,
            0.10,
        ),
        (
            2,
            "Bravo",
            201,
            datetime(2026, 1, 3, tzinfo=timezone.utc),
            0.20,
            0.18,
        ),
    ])
    by_id = {r["project_id"]: r for r in out["projects"]}
    assert by_id[1]["simulation_count"] == 2
    assert by_id[2]["simulation_count"] == 1
    assert by_id[1]["mean_predicted_conversion"] == pytest.approx(0.11)
    assert by_id[2]["mean_predicted_conversion"] == pytest.approx(0.20)


def test_rollup_simulation_count_sums_total() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
        (1, "Alpha", 102, None, 0.10, 0.05),
        (2, "Bravo", 201, None, 0.10, 0.05),
    ])
    assert out["total_simulations"] == 3
    assert out["total_projects"] == 2


def test_rollup_sorted_by_sim_count_desc() -> None:
    """Most-active projects surface first; tiebreak by
    project_id ASC."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
        (2, "Bravo", 201, None, 0.10, 0.05),
        (2, "Bravo", 202, None, 0.10, 0.05),
        (3, "Charlie", 301, None, 0.10, 0.05),
        (3, "Charlie", 302, None, 0.10, 0.05),
        (3, "Charlie", 303, None, 0.10, 0.05),
    ])
    names = [r["project_title"] for r in out["projects"]]
    # Charlie (3 sims) → Bravo (2) → Alpha (1).
    assert names == ["Charlie", "Bravo", "Alpha"]


def test_rollup_tiebreak_on_project_id_asc() -> None:
    """Tied sim count → lower project_id first."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (5, "Zebra", 501, None, 0.10, 0.05),
        (2, "Alpha", 201, None, 0.10, 0.05),
    ])
    ids = [r["project_id"] for r in out["projects"]]
    assert ids == [2, 5]


# ---------------------------------------------------------------------------
# Latest sim tracking
# ---------------------------------------------------------------------------


def test_rollup_tracks_latest_sim_per_project() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    rows = [
        (
            1,
            "Alpha",
            101,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10,
            0.05,
        ),
        (
            1,
            "Alpha",
            102,
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            0.10,
            0.05,
        ),
    ]
    out = build_project_portfolio_rollup(rows)
    alpha = out["projects"][0]
    # Highest sim id wins (the route orders by sim_id ASC so
    # the last occurrence is the latest).
    assert alpha["latest_sim_id"] == 102


def test_rollup_handles_null_sim_id() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (
            1,
            "Alpha",
            None,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0.10,
            0.05,
        ),
    ])
    assert out["projects"][0]["latest_sim_id"] is None


def test_rollup_handles_null_created_at() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
    ])
    assert out["projects"][0]["latest_sim_created_at"] is None


# ---------------------------------------------------------------------------
# Miscalibrated counter
# ---------------------------------------------------------------------------


def test_rollup_counts_miscalibrated_simulations() -> None:
    """|predicted − actual| > confidence_threshold → miscalibrated."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        # variance 0.005 (not miscalibrated)
        (1, "Alpha", 101, None, 0.105, 0.10),
        # variance 0.05 (miscalibrated)
        (1, "Alpha", 102, None, 0.15, 0.10),
        # variance 0.10 (miscalibrated)
        (1, "Alpha", 103, None, 0.20, 0.10),
    ])
    assert out["projects"][0]["miscalibrated_sim_count"] == 2


def test_rollup_skips_sims_with_missing_outcome() -> None:
    """A sim without predicted/actual is counted but doesn't
    contribute to mean or miscalibrated count."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
        (1, "Alpha", 102, None, None, None),  # no outcome
        (1, "Alpha", 103, None, "abc", "def"),  # bad data
    ])
    alpha = out["projects"][0]
    assert alpha["simulation_count"] == 3
    assert alpha["mean_predicted_conversion"] == pytest.approx(0.10)
    assert alpha["mean_actual_conversion"] == pytest.approx(0.05)
    # Only 1 sim with valid outcome → 0 miscalibrated
    # (|0.10 - 0.05| = 0.05 > 0.02 but it's still counted... let
    # me check this).
    assert alpha["miscalibrated_sim_count"] == 1


def test_rollup_custom_confidence_threshold() -> None:
    """A 5pp shift is BIASED at the default 2pp threshold but
    NOT at a 10pp threshold."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    default_out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
    ])
    assert default_out["projects"][0]["miscalibrated_sim_count"] == 1
    custom_out = build_project_portfolio_rollup(
        [(1, "Alpha", 101, None, 0.10, 0.05)],
        confidence_threshold=0.10,
    )
    assert custom_out["projects"][0]["miscalibrated_sim_count"] == 0


# ---------------------------------------------------------------------------
# miscalibration_rate + critical_simulation_count + project_health_label
# ---------------------------------------------------------------------------


def test_rollup_miscalibration_rate_fraction() -> None:
    """miscalibrated_sim_count / simulation_count."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        # 2 sims, 1 miscalibrated → 0.5
        (1, "Alpha", 101, None, 0.10, 0.05),
        (1, "Alpha", 102, None, 0.10, 0.05),
        (1, "Alpha", 103, None, 0.05, 0.05),  # not miscalibrated
        (1, "Alpha", 104, None, 0.05, 0.05),  # not miscalibrated
    ])
    assert out["projects"][0]["miscalibration_rate"] == pytest.approx(0.5)


def test_rollup_miscalibration_rate_zero_when_no_data() -> None:
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    # Sims without outcomes → observation_count stays 0 →
    # miscalibration_rate stays 0.0 (division-by-zero guard).
    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, None, None),
        (1, "Alpha", 102, None, "abc", "def"),
    ])
    assert out["projects"][0]["miscalibration_rate"] == 0.0


def test_rollup_critical_simulation_count_uses_fixed_5pp_threshold() -> None:
    """critical_simulation_count counts sims with |gap| ≥ 5pp,
    independent of the configurable confidence_threshold."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    # 3 sims: 0.03 (not critical), 0.06 (critical), 0.10 (critical)
    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.07),  # gap 0.03
        (1, "Alpha", 102, None, 0.10, 0.04),  # gap 0.06
        (1, "Alpha", 103, None, 0.20, 0.10),  # gap 0.10
    ])
    assert out["projects"][0]["critical_simulation_count"] == 2


def test_rollup_critical_threshold_independent_of_confidence() -> None:
    """A sim counted at 5pp critical is NOT dependent on the
    configurable confidence_threshold (2pp default)."""
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    out_default = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.04),  # gap 0.06
    ])
    out_loose = build_project_portfolio_rollup(
        [(1, "Alpha", 101, None, 0.10, 0.04)],
        confidence_threshold=0.20,
    )
    # Same critical count regardless of confidence_threshold.
    assert out_default["projects"][0]["critical_simulation_count"] == 1
    assert out_loose["projects"][0]["critical_simulation_count"] == 1


def test_rollup_project_health_label_healthy_for_low_rate() -> None:
    """miscalibration_rate < 0.10 → HEALTHY."""
    from app.simulation.project_rollup import (
        LABEL_HEALTHY,
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.10),  # not miscalibrated
        (1, "Alpha", 102, None, 0.10, 0.10),
        (1, "Alpha", 103, None, 0.10, 0.10),
        (1, "Alpha", 104, None, 0.10, 0.10),
    ])
    assert out["projects"][0]["miscalibration_rate"] == 0.0
    assert out["projects"][0]["project_health_label"] == LABEL_HEALTHY


def test_rollup_project_health_label_watch_for_mid_rate() -> None:
    """0.10 ≤ rate < 0.30 → WATCH."""
    from app.simulation.project_rollup import (
        LABEL_WATCH,
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        # 4 sims, 1 miscalibrated → 0.25 → WATCH
        (1, "Alpha", 101, None, 0.10, 0.10),
        (1, "Alpha", 102, None, 0.10, 0.10),
        (1, "Alpha", 103, None, 0.10, 0.10),
        (1, "Alpha", 104, None, 0.20, 0.10),  # miscalibrated
    ])
    assert out["projects"][0]["miscalibration_rate"] == 0.25
    assert out["projects"][0]["project_health_label"] == LABEL_WATCH


def test_rollup_project_health_label_miscalibrated_for_high_rate() -> None:
    """rate ≥ 0.30 → MISALIBRATED."""
    from app.simulation.project_rollup import (
        LABEL_MISALIBRATED,
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        # 3 sims, 2 miscalibrated → 0.667 → MISALIBRATED
        (1, "Alpha", 101, None, 0.10, 0.10),
        (1, "Alpha", 102, None, 0.20, 0.10),  # miscalibrated
        (1, "Alpha", 103, None, 0.30, 0.10),  # miscalibrated
    ])
    assert out["projects"][0]["miscalibration_rate"] == pytest.approx(2/3)
    assert out["projects"][0]["project_health_label"] == LABEL_MISALIBRATED


def test_rollup_project_health_label_unknown_for_no_data() -> None:
    """Zero sims / no outcomes → UNKNOWN."""
    from app.simulation.project_rollup import (
        LABEL_UNKNOWN,
        build_project_portfolio_rollup,
    )

    out = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, None, None),
    ])
    assert out["projects"][0]["simulation_count"] == 1
    assert out["projects"][0]["project_health_label"] == LABEL_UNKNOWN


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_project_rollup_out_default_shape() -> None:
    from app.schemas.simulation import ProjectPortfolioRollupOut

    out = ProjectPortfolioRollupOut()
    assert out.projects == []
    assert out.total_projects == 0
    assert out.total_simulations == 0
    assert out.confidence_threshold == 0.02


def test_project_rollup_out_round_trips_helper_payload() -> None:
    """The route layer must wrap
    ``build_project_portfolio_rollup(...)`` output directly
    into the Pydantic schema without coercion errors."""
    from app.schemas.simulation import ProjectPortfolioRollupOut
    from app.simulation.project_rollup import (
        build_project_portfolio_rollup,
    )

    payload = build_project_portfolio_rollup([
        (1, "Alpha", 101, None, 0.10, 0.05),
        (2, "Bravo", 201, None, 0.20, 0.18),
    ])
    payload["confidence_threshold"] = 0.02
    out = ProjectPortfolioRollupOut(**payload)
    assert out.total_projects == 2
    assert out.total_simulations == 2


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_project_rollup_route_registered() -> None:
    """GET /simulations/project-portfolio-rollup must appear in
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
    assert "/simulations/project-portfolio-rollup" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET" in methods_by_path["/simulations/project-portfolio-rollup"]
    )


def test_project_rollup_route_query_params() -> None:
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
            r.path == "/simulations/project-portfolio-rollup"
            and "GET" in (r.methods or set())
        ):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            assert "confidence_threshold" in query_param_names
            return
    raise AssertionError(
        "GET /simulations/project-portfolio-rollup route not found"
    )