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
    assert out.status_counts == {}
    assert out.filtered_by_since is None


def test_batch_status_out_with_data() -> None:
    from app.schemas.simulation import SimulationBatchStatusOut

    out = SimulationBatchStatusOut(
        items=[],
        not_found=[5, 7],
        requested=3,
        status_counts={"COMPLETED": 2, "FAILED": 1},
    )
    assert out.not_found == [5, 7]
    assert out.requested == 3
    assert out.status_counts == {"COMPLETED": 2, "FAILED": 1}


# ---------------------------------------------------------------------------
# parse_since — ISO 8601 timestamp parsing
# ---------------------------------------------------------------------------


def test_parse_since_none_returns_none() -> None:
    from app.simulation.sim_batch import parse_since

    assert parse_since(None) is None
    assert parse_since("") is None
    assert parse_since("   ") is None


def test_parse_since_accepts_z_suffix() -> None:
    from app.simulation.sim_batch import parse_since

    parsed = parse_since("2026-07-26T00:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 7 and parsed.day == 26


def test_parse_since_accepts_offset() -> None:
    from app.simulation.sim_batch import parse_since

    parsed = parse_since("2026-07-26T05:30:00+05:30")
    assert parsed is not None
    # Always normalised to UTC for consistent DB comparison.
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.hour == 0  # 05:30 IST == 00:00 UTC


def test_parse_since_rejects_naive() -> None:
    """Force callers to be timezone-aware — naive timestamps would
    silently mismatch across regions."""
    from app.simulation.sim_batch import parse_since

    with pytest.raises(ValueError):
        parse_since("2026-07-26T00:00:00")


def test_parse_since_rejects_garbage() -> None:
    from app.simulation.sim_batch import parse_since

    with pytest.raises(ValueError):
        parse_since("not a date")
    with pytest.raises(ValueError):
        parse_since("2026-13-01T00:00:00Z")  # month 13


# ---------------------------------------------------------------------------
# summarise_statuses
# ---------------------------------------------------------------------------


def test_summarise_statuses_counts_each_status() -> None:
    from app.simulation.sim_batch import summarise_statuses

    out = summarise_statuses(
        ["COMPLETED", "FAILED", "COMPLETED", "RUNNING", "COMPLETED"]
    )
    assert out == {"COMPLETED": 3, "FAILED": 1, "RUNNING": 1}


def test_summarise_statuses_empty_input() -> None:
    from app.simulation.sim_batch import summarise_statuses

    assert summarise_statuses([]) == {}


def test_summarise_statuses_drops_non_strings_and_empty() -> None:
    """Defensive — the DB column is String(50) but the helper is pure
    and may be called with foreign data (e.g. from a fixture)."""
    from app.simulation.sim_batch import summarise_statuses

    out = summarise_statuses(["COMPLETED", 123, None, "", "FAILED"])  # type: ignore[list-item]
    assert out == {"COMPLETED": 1, "FAILED": 1}


# ---------------------------------------------------------------------------
# Sort + order (batch-specific allowlist)
# ---------------------------------------------------------------------------


def test_batch_sort_defaults_to_id_asc() -> None:
    from app.simulation.sim_batch import (
        DEFAULT_BATCH_ORDER,
        DEFAULT_BATCH_SORT,
    )
    assert DEFAULT_BATCH_SORT == "id"
    assert DEFAULT_BATCH_ORDER == "asc"


def test_batch_sort_accepts_allowed_values() -> None:
    from app.simulation.sim_batch import VALID_BATCH_SORT_FIELDS

    assert set(VALID_BATCH_SORT_FIELDS.keys()) == {"id", "updated_at"}


def test_batch_order_is_frozen() -> None:
    from app.simulation.sim_batch import VALID_BATCH_ORDERS

    assert set(VALID_BATCH_ORDERS) == {"asc", "desc"}
    with pytest.raises(AttributeError):
        VALID_BATCH_ORDERS.add("random")  # type: ignore[attr-defined]


def test_batch_normalise_sort_case_insensitive() -> None:
    from app.simulation.sim_batch import _normalise_sort

    assert _normalise_sort("UPDATED_AT") == "updated_at"
    assert _normalise_sort(None) == "id"
    assert _normalise_sort("") == "id"


def test_batch_normalise_sort_rejects_unknown() -> None:
    from app.simulation.sim_batch import _normalise_sort

    with pytest.raises(ValueError):
        _normalise_sort("title")  # not allowed in batch endpoint
    with pytest.raises(ValueError):
        _normalise_sort("created_at")  # not allowed in batch endpoint


def test_batch_normalise_order_case_insensitive() -> None:
    from app.simulation.sim_batch import _normalise_order

    assert _normalise_order("DESC") == "desc"
    assert _normalise_order(None) == "asc"


def test_batch_normalise_order_rejects_unknown() -> None:
    from app.simulation.sim_batch import _normalise_order

    with pytest.raises(ValueError):
        _normalise_order("descending")
    with pytest.raises(ValueError):
        _normalise_order("ascending")


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
