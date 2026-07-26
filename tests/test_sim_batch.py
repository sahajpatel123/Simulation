"""
Tests for the bulk simulation-status helper + schema + route.

The DB-touching batch query is smoke-tested via the route
registration pattern (gated by ``scipy`` availability, like the
other route tests).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pure helpers — ``parse_id_list``
# ---------------------------------------------------------------------------


def test_empty_inputs_return_empty_list() -> None:
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list(None) == []
    assert parse_id_list([]) == []
    assert parse_id_list([""]) == []
    assert parse_id_list([","]) == []


def test_simple_int_strings_parse() -> None:
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list(["1", "2", "3"]) == [1, 2, 3]


def test_comma_separated_tokens_are_split() -> None:
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list(["1,2,3"]) == [1, 2, 3]
    assert parse_id_list(["1, 2 , 3"]) == [1, 2, 3]


def test_whitespace_is_stripped() -> None:
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list(["  1  ", "\t2\n"]) == [1, 2]


def test_duplicates_are_dropped_first_wins() -> None:
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list(["1", "2", "1", "3", "2"]) == [1, 2, 3]


def test_invalid_token_raises() -> None:
    from app.simulation.sim_batch import parse_id_list

    with pytest.raises(ValueError):
        parse_id_list(["abc"])
    with pytest.raises(ValueError):
        parse_id_list(["1.5"])  # not an int
    with pytest.raises(ValueError):
        parse_id_list(["1, abc, 2"])


def test_zero_or_negative_id_raises() -> None:
    from app.simulation.sim_batch import parse_id_list

    with pytest.raises(ValueError):
        parse_id_list(["0"])
    with pytest.raises(ValueError):
        parse_id_list(["-1"])


def test_over_cap_raises() -> None:
    from app.simulation.sim_batch import MAX_BATCH_SIZE, parse_id_list

    too_many = [str(i) for i in range(1, MAX_BATCH_SIZE + 2)]
    with pytest.raises(ValueError):
        parse_id_list(too_many)


def test_at_cap_is_ok() -> None:
    from app.simulation.sim_batch import MAX_BATCH_SIZE, parse_id_list

    at_cap = [str(i) for i in range(1, MAX_BATCH_SIZE + 1)]
    assert parse_id_list(at_cap) == list(range(1, MAX_BATCH_SIZE + 1))


def test_none_entries_skipped() -> None:
    """Defensive: a None token shouldn't crash the parser."""
    from app.simulation.sim_batch import parse_id_list

    assert parse_id_list([None, "1", None]) == [1]  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_batch_status_out_default_shape() -> None:
    from app.schemas.simulation import SimulationBatchStatusOut

    out = SimulationBatchStatusOut(items=[], not_found=[], requested=0)
    assert out.items == []
    assert out.not_found == []
    assert out.requested == 0


def test_batch_status_out_with_data() -> None:
    from app.schemas.simulation import SimulationBatchStatusOut

    out = SimulationBatchStatusOut(
        items=[],
        not_found=[5, 7],
        requested=3,
    )
    assert out.not_found == [5, 7]
    assert out.requested == 3


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_batch_route_registered() -> None:
    """GET /simulations/batch must appear in the router."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/batch" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/simulations/batch"]


def test_batch_route_query_param_ids() -> None:
    """The batch route must expose the ``ids`` query param so the
    UI can call ``GET /simulations/batch?ids=1&ids=2&ids=3``."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import simulations as sim_mod

    for r in sim_mod.router.routes:
        if r.path == "/simulations/batch" and "GET" in (r.methods or set()):
            query_param_names = {p.name for p in r.dependant.query_params}
            assert "ids" in query_param_names
            return
    raise AssertionError("GET /simulations/batch route not found")