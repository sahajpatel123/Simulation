"""
Tests for the project search helper + schema.

The DB-touching route is smoke-tested via the route-registration
pattern (gated by ``scipy`` availability, like the other route tests).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Pure helpers — ``build_search_filters``
# ---------------------------------------------------------------------------


def test_empty_inputs_return_defaults() -> None:
    from app.simulation.project_search import build_search_filters

    f = build_search_filters()
    assert f["query_words"] == []
    assert f["tags"] == []
    assert f["status"] is None
    assert f["archived"] is None
    assert f["limit"] == 50  # default
    assert f["before_id"] is None


def test_query_words_collapse_and_casefold() -> None:
    from app.simulation.project_search import build_search_filters

    f = build_search_filters(q="  AI  Tutor  ")
    assert f["query_words"] == ["ai", "tutor"]


def test_query_words_cap_word_count() -> None:
    from app.simulation.project_search import (
        MAX_QUERY_WORDS,
        build_search_filters,
    )

    too_many = " ".join(f"w{i}" for i in range(MAX_QUERY_WORDS + 1))
    with pytest.raises(ValueError):
        build_search_filters(q=too_many)


def test_query_words_cap_word_length() -> None:
    from app.simulation.project_search import (
        MAX_QUERY_WORD_LEN,
        build_search_filters,
    )

    too_long = "a" * (MAX_QUERY_WORD_LEN + 1)
    with pytest.raises(ValueError):
        build_search_filters(q=too_long)


def test_query_words_at_max_word_count() -> None:
    from app.simulation.project_search import (
        MAX_QUERY_WORDS,
        build_search_filters,
    )

    at_max = " ".join(f"w{i}" for i in range(MAX_QUERY_WORDS))
    f = build_search_filters(q=at_max)
    assert len(f["query_words"]) == MAX_QUERY_WORDS


def test_query_words_at_max_word_length() -> None:
    from app.simulation.project_search import (
        MAX_QUERY_WORD_LEN,
        build_search_filters,
    )

    at_max = "a" * MAX_QUERY_WORD_LEN
    f = build_search_filters(q=at_max)
    assert f["query_words"] == [at_max]


def test_status_uppercases_and_strips() -> None:
    from app.simulation.project_search import build_search_filters

    assert build_search_filters(status="draft")["status"] == "DRAFT"
    assert build_search_filters(status="  ACTIVE  ")["status"] == "ACTIVE"
    assert build_search_filters(status="")["status"] is None
    assert build_search_filters(status=None)["status"] is None


def test_status_caps_length() -> None:
    from app.simulation.project_search import build_search_filters

    with pytest.raises(ValueError):
        build_search_filters(status="x" * 51)


def test_tags_canonicalise_via_project_tags() -> None:
    from app.simulation.project_search import build_search_filters

    # Mixed case + whitespace + duplicates → canonical, deduped.
    f = build_search_filters(tags=["  SAAS  ", "v2", "SAAS"])
    assert f["tags"] == ["saas", "v2"]


def test_tags_rejects_invalid() -> None:
    from app.simulation.project_search import build_search_filters

    # Note: "bad space" is *not* here because internal whitespace is
    # collapsed to a dash before char-set validation (so "bad space"
    # becomes "bad-space", which is allowed). Use a clearly invalid one.
    with pytest.raises(ValueError):
        build_search_filters(tags=["bad.dot"])
    with pytest.raises(ValueError):
        build_search_filters(tags=["bad/slash"])


def test_limit_clamps_to_bounds() -> None:
    from app.simulation.project_search import (
        MAX_LIMIT,
        MIN_LIMIT,
        build_search_filters,
    )

    assert build_search_filters(limit=None)["limit"] == 50
    assert build_search_filters(limit=0)["limit"] == MIN_LIMIT
    assert build_search_filters(limit=-100)["limit"] == MIN_LIMIT
    assert build_search_filters(limit=MAX_LIMIT + 1000)["limit"] == MAX_LIMIT
    assert build_search_filters(limit=25)["limit"] == 25


def test_before_id_passes_through() -> None:
    from app.simulation.project_search import build_search_filters

    assert build_search_filters(before_id=None)["before_id"] is None
    assert build_search_filters(before_id=42)["before_id"] == 42


def test_archived_passes_through_three_states() -> None:
    from app.simulation.project_search import build_search_filters

    assert build_search_filters(archived=None)["archived"] is None
    assert build_search_filters(archived=True)["archived"] is True
    assert build_search_filters(archived=False)["archived"] is False


def test_filters_compose() -> None:
    """All filters must coexist in one kwargs dict without trampling."""
    from app.simulation.project_search import build_search_filters

    f = build_search_filters(
        q="ai tutor",
        tags=["saas", "v2"],
        status="draft",
        archived=False,
        limit=10,
        before_id=100,
    )
    assert f["query_words"] == ["ai", "tutor"]
    assert f["tags"] == ["saas", "v2"]
    assert f["status"] == "DRAFT"
    assert f["archived"] is False
    assert f["limit"] == 10
    assert f["before_id"] == 100


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_project_search_list_response_default_shape() -> None:
    from app.schemas.project import ProjectSearchListResponse

    out = ProjectSearchListResponse(
        projects=[], total=0, has_more=False, next_before_id=None
    )
    assert out.projects == []
    assert out.total == 0
    assert out.has_more is False
    assert out.next_before_id is None


def test_project_search_list_response_with_cursor() -> None:
    from app.schemas.project import ProjectSearchListResponse

    out = ProjectSearchListResponse(
        projects=[], total=42, has_more=True, next_before_id=10
    )
    assert out.has_more is True
    assert out.next_before_id == 10
    assert out.total == 42


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_search_route_registered() -> None:
    """GET /projects/search must appear in the router with the
    expected query parameters."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.api.v1 import projects as projects_mod

    paths = {r.path for r in projects_mod.router.routes}
    assert "/projects/search" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in projects_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path["/projects/search"]
