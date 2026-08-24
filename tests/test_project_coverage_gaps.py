"""Tests for the per-project coverage-gaps endpoint.

The helper itself is covered by ``test_coverage_gaps.py``; these tests pin
the project-scoped schema shape, the route registration, and the route
handler's behavior with fake session rows (no DB).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_project_coverage_gaps_out_default_shape() -> None:
    from app.schemas.project import ProjectCoverageGapsOut

    out = ProjectCoverageGapsOut()
    assert out.project_id == 0
    assert out.project_title is None
    assert out.covered_categories == []
    assert out.missing_categories == []
    assert out.sensitivity_breakdown == {}
    assert out.covered_cluster_count == 0
    assert out.total_assumption_count == 0
    assert out.key_signals == []


def test_project_coverage_gaps_out_round_trips_helper_payload() -> None:
    from app.schemas.project import ProjectCoverageGapsOut
    from app.simulation.coverage_gaps import build_coverage_gaps

    payload = build_coverage_gaps(
        assumptions=[
            {"category": "Pricing", "sensitivity": "HIGH",
             "is_hidden": False},
        ],
        cluster_ids=[1, 2, 3],
    )
    payload["project_id"] = 7
    payload["project_title"] = "Pricing idea"
    out = ProjectCoverageGapsOut(**payload)
    assert out.project_id == 7
    assert out.project_title == "Pricing idea"
    assert "Pricing" in out.covered_categories
    assert out.covered_cluster_count == 3


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_project_coverage_gaps_route_registered() -> None:
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
    assert (
        "/projects/{project_id}/coverage-gaps" in paths
    )

    methods_by_path: dict[str, set[str]] = {}
    for r in proj_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(
            r.methods or set()
        )
    assert (
        "GET"
        in methods_by_path[
            "/projects/{project_id}/coverage-gaps"
        ]
    )


# ---------------------------------------------------------------------------
# Route handler (fake session)
# ---------------------------------------------------------------------------


class _FakeAssumption:
    def __init__(
        self,
        category: str,
        sensitivity: str,
        is_hidden: bool = False,
    ) -> None:
        self.category = category
        self.sensitivity = sensitivity
        self.is_hidden = is_hidden


class _FakeProject:
    title = "Project X"


class _FakeQuery:
    def __init__(self, rows: list[object], first_row: object = None) -> None:
        self.rows = rows
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.first_row

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(
        self,
        assumptions: list[object] | None = None,
        sim_results: list[dict] | None = None,
        raw_sim_rows: list[tuple[object]] | None = None,
    ) -> None:
        self.assumptions = assumptions or []
        self.sim_results = sim_results or []
        self.raw_sim_rows = raw_sim_rows

    def query(self, *args, **kwargs):
        target = args[0] if args else None
        class_ = getattr(target, "class_", target)
        name = getattr(class_, "__name__", "")
        if name == "Project":
            return _FakeQuery(rows=[], first_row=_FakeProject())
        if name == "Assumption":
            return _FakeQuery(rows=self.assumptions)
        if name == "Simulation":
            if self.raw_sim_rows is not None:
                return _FakeQuery(rows=self.raw_sim_rows)
            return _FakeQuery(rows=[(raw,) for raw in self.sim_results])
        return _FakeQuery(rows=[])


def _call_route(
    *,
    current_user_id: int = 42,
    project_id: int = 1,
    assumptions: list[object] | None = None,
    sim_results: list[dict] | None = None,
    raw_sim_rows: list[tuple[object]] | None = None,
):
    from app.api.v1 import projects as proj_mod

    return proj_mod.get_project_coverage_gaps(
        project_id=project_id,
        db=_FakeSession(
            assumptions=assumptions,
            sim_results=sim_results,
            raw_sim_rows=raw_sim_rows,
        ),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_project_coverage_gaps_empty_state() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route()
    assert out.project_id == 1
    assert out.project_title == "Project X"
    assert out.total_assumption_count == 0
    assert out.covered_cluster_count == 0
    assert "Pricing" in out.missing_categories


def test_project_coverage_gaps_uses_project_rows() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route(
        assumptions=[
            _FakeAssumption("Pricing", "HIGH"),
            _FakeAssumption("Trust", "MEDIUM"),
        ],
        sim_results=[
            {"cluster_breakdown": {"1": {"conversion_rate": 0.05}, "2": {}}},
            {"cluster_breakdown": {"2": {}, "3": {}}},
        ],
    )
    assert out.project_id == 1
    assert "Pricing" in out.covered_categories
    assert "Trust" in out.covered_categories
    assert "Retention" in out.missing_categories
    assert out.total_assumption_count == 2
    assert out.covered_cluster_count == 3


def test_project_coverage_gaps_handles_string_results_json() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route(
        assumptions=[],
        sim_results=[
            '{"cluster_breakdown": {"7": {}}}',
        ],
    )
    assert out.covered_cluster_count == 1


def test_project_coverage_gaps_handles_malformed_results_json() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    # A corrupted legacy text row should not take the digest down.
    out = _call_route(
        assumptions=[],
        raw_sim_rows=[
            ("{not valid json",),
            ("[1, 2, 3]",),
        ],
    )
    assert out.covered_cluster_count == 0
    assert out.total_assumption_count == 0
    assert "Pricing" in out.missing_categories


def test_project_coverage_gaps_excludes_hidden_assumptions() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route(
        assumptions=[
            _FakeAssumption("Pricing", "HIGH"),
            _FakeAssumption("Trust", "LOW", is_hidden=True),
        ],
    )
    assert out.total_assumption_count == 1
    assert "Pricing" in out.covered_categories
    assert "Trust" in out.missing_categories
    assert out.sensitivity_breakdown.get("HIGH") == 1
    assert "LOW" not in out.sensitivity_breakdown


def test_project_coverage_gaps_counts_string_cluster_ids() -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    out = _call_route(
        sim_results=[
            {
                "cluster_breakdown": {
                    "metro_power_professional": {"conversion_rate": 0.06},
                    "young_urban_professional_first_job": {},
                }
            },
        ],
    )
    assert out.covered_cluster_count == 2
